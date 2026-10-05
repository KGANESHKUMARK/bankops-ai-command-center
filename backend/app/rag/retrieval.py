"""Authorized hybrid retrieval with citations, sufficiency assessment and metrics.

Pipeline: SQL authorization filter -> semantic (vector) + keyword (BM25) ranking
-> Reciprocal Rank Fusion -> optional lexical reranker -> defense-in-depth
per-result authorization re-check -> injection neutralization -> citations.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import DocumentStatus
from app.models import KnowledgeChunk, KnowledgeDocument, RetrievalLog
from app.policy.engine import Actor, PolicyEngine
from app.rag.embeddings import Embedder, EmbeddingError
from app.rag.injection import neutralize
from app.rag.keyword import bm25_scores, term_coverage
from app.rag.store import ChunkFilter, candidate_chunks, semantic_search
from app.services.flags import fault_enabled

log = get_logger("rag.retrieval")
RRF_K = 60
UNVERIFIED_PENALTY = 0.75  # documents tagged "unverified" rank below approved sources
Mode = Literal["hybrid", "semantic", "keyword"]


class RetrievalError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    doc_key: str
    title: str
    version: str
    section: str
    chunk_index: int
    classification: str
    content: str
    semantic_score: float
    keyword_score: float
    fused_score: float
    rerank_score: float
    injection_detected: bool
    injection_patterns: list[str] = field(default_factory=list)
    trust: str = "approved"

    @property
    def chunk_ref(self) -> str:
        return f"{self.doc_key}@{self.version}#chunk-{self.chunk_index}"

    def citation(self) -> str:
        return f"{self.title} (v{self.version}) - {self.section} [{self.chunk_ref}]"

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["chunk_ref"] = self.chunk_ref
        data["citation"] = self.citation()
        return data


@dataclass
class RetrievalResult:
    query: str
    mode: str
    results: list[RetrievedChunk]
    sufficient: bool
    top_score: float | None
    excluded_unauthorized: int
    latency_ms: int
    index_version: str
    reason: str
    candidate_count: int


class Retriever:
    def __init__(self, settings: Settings, embedder: Embedder) -> None:
        self.settings = settings
        self.embedder = embedder

    def _resolve_tag_docs(self, db: Session, tenant_id: str, tags: tuple[str, ...]) -> tuple[str, ...]:
        docs = db.execute(
            select(KnowledgeDocument.id, KnowledgeDocument.tags).where(
                KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.deleted_at.is_(None)
            )
        ).all()
        wanted = set(tags)
        return tuple(doc_id for doc_id, doc_tags in docs if wanted & set(doc_tags or [])) or ("__none__",)

    def search(
        self,
        db: Session,
        actor: Actor,
        query: str,
        *,
        top_k: int | None = None,
        mode: Mode | None = None,
        classifications: tuple[str, ...] = (),
        document_ids: tuple[str, ...] = (),
        tags: tuple[str, ...] = (),
        investigation_id: str | None = None,
        log_query: bool = True,
    ) -> RetrievalResult:
        started = time.perf_counter()
        top_k = max(1, min(top_k or self.settings.retrieval_top_k, 20))
        mode = mode or self.settings.retrieval_mode
        query = " ".join(query.split())[:500]
        error_code: str | None = None
        result: RetrievalResult | None = None
        try:
            if fault_enabled(db, "retrieval_failure"):
                raise RetrievalError("retrieval_unavailable_injected")
            if tags:
                document_ids = tuple(set(document_ids) | set(self._resolve_tag_docs(db, actor.tenant_id, tags)))
            flt = ChunkFilter(
                tenant_id=actor.tenant_id,
                role=actor.role,
                index_version=self.settings.index_version,
                document_ids=document_ids,
                classifications=classifications,
            )
            result = self._search(db, actor, query, flt, top_k=top_k, mode=mode)
        except EmbeddingError as exc:
            error_code = exc.code
            raise RetrievalError(exc.code) from exc
        except RetrievalError as exc:
            error_code = exc.code
            raise
        finally:
            latency = int((time.perf_counter() - started) * 1000)
            if log_query:
                db.add(
                    RetrievalLog(
                        tenant_id=actor.tenant_id,
                        user_id=actor.user_id,
                        investigation_id=investigation_id,
                        query_preview=query[:200],
                        mode=mode,
                        top_k=top_k,
                        result_count=len(result.results) if result else 0,
                        excluded_unauthorized=result.excluded_unauthorized if result else 0,
                        top_score=result.top_score if result else None,
                        latency_ms=latency,
                        sufficient=bool(result and result.sufficient),
                        error_code=error_code,
                    )
                )
                db.flush()
        result.latency_ms = latency
        return result

    def _search(
        self, db: Session, actor: Actor, query: str, flt: ChunkFilter, *, top_k: int, mode: str
    ) -> RetrievalResult:
        s = self.settings
        pool = top_k * 4
        candidates = candidate_chunks(db, flt, max_candidates=s.retrieval_max_candidates)
        by_id = {c.id: c for c in candidates}
        tenant_total = db.execute(
            select(func.count(KnowledgeChunk.id))
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(
                KnowledgeChunk.tenant_id == actor.tenant_id,
                KnowledgeChunk.index_version == s.index_version,
                KnowledgeDocument.status == DocumentStatus.INDEXED.value,
                KnowledgeDocument.deleted_at.is_(None),
            )
        ).scalar_one()
        excluded = max(0, int(tenant_total) - len(candidates)) if not (flt.document_ids or flt.classifications) else 0

        semantic: dict[str, float] = {}
        keyword: dict[str, float] = {}
        if candidates and mode in ("hybrid", "semantic"):
            qvec = self.embedder.embed([query])[0]
            for chunk, score in semantic_search(db, qvec, flt, k=pool, max_candidates=s.retrieval_max_candidates):
                semantic[chunk.id] = score
                by_id.setdefault(chunk.id, chunk)
        if candidates and mode in ("hybrid", "keyword"):
            docs = {c.document_id: c for c in candidates}
            titles = self._titles(db, list(docs))
            texts = [f"{titles.get(c.document_id, '')} {c.section} {c.content}" for c in candidates]
            for chunk, score in zip(candidates, bm25_scores(query, texts), strict=True):
                if score > 0:
                    keyword[chunk.id] = score

        fused: dict[str, float] = {}
        for ranking in (semantic, keyword):
            for rank, cid in enumerate(sorted(ranking, key=lambda c: -ranking[c])[:pool], start=1):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)
        ranked = sorted(fused, key=lambda c: -fused[c])[: pool]

        titles = self._titles(db, list({by_id[c].document_id for c in ranked}))
        docs_meta = self._doc_meta(db, list({by_id[c].document_id for c in ranked}))
        max_kw = max(keyword.values(), default=0.0) or 1.0
        results: list[RetrievedChunk] = []
        for cid in ranked:
            chunk = by_id[cid]
            meta = docs_meta[chunk.document_id]
            # Defense in depth: re-verify authorization on every result before it leaves this module.
            if not PolicyEngine.can_read_document(
                actor, tenant_id=meta.tenant_id, classification=meta.classification, allowed_roles=meta.allowed_roles
            ):
                log.warning("authorization re-check removed a retrieval result", extra={"chunk_id": cid})
                continue
            sem = semantic.get(cid, 0.0)
            kw = keyword.get(cid, 0.0)
            text = f"{titles.get(chunk.document_id, '')} {chunk.section} {chunk.content}"
            rerank = (
                0.55 * max(sem, 0.0) + 0.25 * (kw / max_kw) + 0.20 * term_coverage(query, text)
                if s.reranker == "lexical"
                else fused[cid]
            )
            trust = "unverified" if "unverified" in (meta.tags or []) else "approved"
            if trust == "unverified":
                rerank *= UNVERIFIED_PENALTY
            sanitized = neutralize(chunk.content)
            results.append(
                RetrievedChunk(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    doc_key=meta.doc_key,
                    title=meta.title,
                    version=meta.version,
                    section=chunk.section,
                    chunk_index=chunk.chunk_index,
                    classification=chunk.classification,
                    content=sanitized.text,
                    semantic_score=round(sem, 4),
                    keyword_score=round(kw, 4),
                    fused_score=round(fused[cid], 5),
                    rerank_score=round(rerank, 4),
                    injection_detected=chunk.injection_detected or sanitized.detected,
                    injection_patterns=sorted(set(chunk.injection_patterns or []) | set(sanitized.pattern_ids)),
                    trust=trust,
                )
            )
        results.sort(key=lambda r: -r.rerank_score)
        results = results[:top_k]
        top = results[0] if results else None
        top_score = max((r.semantic_score for r in results), default=None) if mode != "keyword" else None
        if not results:
            sufficient, reason = False, "No authorized knowledge matched the query."
        elif mode == "keyword":
            sufficient = top is not None and top.keyword_score > 0 and term_coverage(query, top.content) >= 0.3
            reason = "Keyword evidence found." if sufficient else "Keyword matches are weak."
        else:
            best_sem = top_score or 0.0
            coverage = max(term_coverage(query, f"{r.title} {r.section} {r.content}") for r in results)
            sufficient = best_sem >= s.retrieval_min_score and coverage >= 0.25
            reason = (
                f"Top semantic score {best_sem:.2f} >= {s.retrieval_min_score:.2f} with term coverage {coverage:.2f}."
                if sufficient
                else f"Weak evidence: top semantic score {best_sem:.2f}, term coverage {coverage:.2f}."
            )
        return RetrievalResult(
            query=query,
            mode=mode,
            results=results,
            sufficient=sufficient,
            top_score=top_score,
            excluded_unauthorized=excluded,
            latency_ms=0,
            index_version=s.index_version,
            reason=reason,
            candidate_count=len(candidates),
        )

    @staticmethod
    def _titles(db: Session, doc_ids: list[str]) -> dict[str, str]:
        if not doc_ids:
            return {}
        return dict(
            db.execute(select(KnowledgeDocument.id, KnowledgeDocument.title).where(KnowledgeDocument.id.in_(doc_ids)))
            .tuples()
            .all()
        )

    @staticmethod
    def _doc_meta(db: Session, doc_ids: list[str]) -> dict[str, KnowledgeDocument]:
        if not doc_ids:
            return {}
        return {d.id: d for d in db.execute(select(KnowledgeDocument).where(KnowledgeDocument.id.in_(doc_ids))).scalars()}
