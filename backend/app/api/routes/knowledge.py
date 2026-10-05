from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import ContainerDep, CurrentUser, DbDep, document_or_404, require
from app.api.pagination import PageParam, PageSizeParam
from app.api.serializers import document_out
from app.core.errors import ApiError
from app.domain import CLASSIFICATION_RANK, Classification, clearance_rank
from app.models import KnowledgeChunk, KnowledgeDocument, RetrievalLog
from app.policy.engine import PolicyEngine
from app.policy.permissions import Permission, has_permission
from app.rag.ingestion import DocumentConflictError, DuplicateDocumentError, IngestRequest
from app.rag.injection import PATTERN_CATALOG
from app.rag.loaders import DocumentLoadError
from app.rag.retrieval import RetrievalError
from app.schemas import SearchRequest
from app.services.metrics import percentile

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/documents", summary="Knowledge documents the caller is authorized to see")
def list_documents(
    db: DbDep,
    container: ContainerDep,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    include_deleted: bool = False,
    current: CurrentUser = Depends(require(Permission.KNOWLEDGE_READ)),
) -> dict[str, Any]:
    actor = current.actor
    q = select(KnowledgeDocument).where(KnowledgeDocument.tenant_id == actor.tenant_id)
    if not (include_deleted and has_permission(actor.role, Permission.KNOWLEDGE_MANAGE)):
        q = q.where(KnowledgeDocument.deleted_at.is_(None))
    docs = [d for d in db.execute(q.order_by(KnowledgeDocument.doc_key, KnowledgeDocument.version)).scalars()
            if PolicyEngine.can_read_document(actor, tenant_id=d.tenant_id, classification=d.classification,
                                              allowed_roles=d.allowed_roles)]
    start = (page - 1) * page_size
    return {"items": [document_out(d, container.settings) for d in docs[start:start + page_size]], "total": len(docs),
            "page": page, "page_size": page_size, "synthetic": True}


@router.get("/stats", summary="Index status and retrieval metrics (measured from retrieval logs)")
def knowledge_stats(db: DbDep, container: ContainerDep,
                    current: CurrentUser = Depends(require(Permission.KNOWLEDGE_READ))) -> dict[str, Any]:
    s = container.settings
    tenant = current.actor.tenant_id
    docs = db.execute(select(KnowledgeDocument).where(KnowledgeDocument.tenant_id == tenant,
                                                      KnowledgeDocument.deleted_at.is_(None))).scalars().all()
    chunks = db.execute(select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.tenant_id == tenant)).scalar_one()
    logs = db.execute(select(RetrievalLog).where(RetrievalLog.tenant_id == tenant)
                      .order_by(RetrievalLog.created_at.desc()).limit(500)).scalars().all()
    lat = [log_.latency_ms for log_ in logs]
    return {
        "index_version": s.index_version, "vector_backend": s.vector_backend,
        "embedding": {"provider": container.embedder.provider, "model": container.embedder.model, "dim": s.embedding_dim},
        "chunking": {"chunk_size": s.chunk_size, "chunk_overlap": s.chunk_overlap},
        "retrieval": {"mode": s.retrieval_mode, "top_k": s.retrieval_top_k, "min_score": s.retrieval_min_score,
                      "reranker": s.reranker, "fusion": "reciprocal-rank-fusion(k=60)"},
        "documents": len(docs), "chunks": int(chunks),
        "stale_documents": sum(1 for d in docs if d.index_version != s.index_version),
        "failed_documents": sum(1 for d in docs if d.status == "failed"),
        "injection_flagged_documents": sum(1 for d in docs if d.injection_flag_count),
        "injection_patterns": PATTERN_CATALOG,
        "retrieval_metrics": {
            "source": "measured (last 500 retrieval log entries)", "queries": len(logs),
            "latency_ms_p50": percentile([float(x) for x in lat], 50), "latency_ms_p95": percentile([float(x) for x in lat], 95),
            "sufficiency_rate": round(sum(1 for x in logs if x.sufficient) / len(logs), 3) if logs else None,
            "errors": sum(1 for x in logs if x.error_code),
            "avg_excluded_unauthorized": round(sum(x.excluded_unauthorized for x in logs) / len(logs), 2) if logs else None,
        },
    }


@router.get("/documents/{doc_id}", summary="Document metadata and chunk inspection")
def get_document(doc_id: str, db: DbDep, container: ContainerDep,
                 current: CurrentUser = Depends(require(Permission.KNOWLEDGE_READ))) -> dict[str, Any]:
    doc = document_or_404(db, current.actor, doc_id)
    chunks = db.execute(select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id)
                        .order_by(KnowledgeChunk.chunk_index)).scalars().all()
    return {**document_out(doc, container.settings), "chunks": [
        {"id": c.id, "chunk_index": c.chunk_index, "section": c.section, "content": c.content, "char_count": c.char_count,
         "token_estimate": c.token_estimate, "embedding_model": c.embedding_model, "index_version": c.index_version,
         "injection_detected": c.injection_detected, "injection_patterns": c.injection_patterns,
         "chunk_ref": f"{doc.doc_key}@{doc.version}#chunk-{c.chunk_index}"} for c in chunks]}


@router.post("/ingest", status_code=status.HTTP_201_CREATED, summary="Upload and index a synthetic knowledge document")
async def ingest(
    db: DbDep,
    container: ContainerDep,
    file: Annotated[UploadFile, File(description=".md, .markdown, .txt or .pdf (max size enforced)")],
    title: Annotated[str, Form(min_length=3, max_length=200)],
    doc_key: Annotated[str, Form(min_length=3, max_length=64)],
    version: Annotated[str, Form(max_length=16)] = "1.0",
    classification: Annotated[Classification, Form()] = Classification.INTERNAL,
    allowed_roles: Annotated[str, Form(max_length=200)] = "demo_admin,operations_manager,operations_analyst,auditor",
    tags: Annotated[str, Form(max_length=300)] = "",
    current: CurrentUser = Depends(require(Permission.KNOWLEDGE_INGEST)),
) -> dict[str, Any]:
    actor = current.actor
    if CLASSIFICATION_RANK[classification] > clearance_rank(actor.role):
        raise ApiError(403, "forbidden", "You cannot upload documents above your own clearance.")
    data = await file.read(container.settings.max_upload_bytes + 1)
    req = IngestRequest(
        filename=file.filename or "upload.txt", data=data, title=title, doc_key=doc_key.upper(), version=version,
        classification=classification, allowed_roles=[r.strip() for r in allowed_roles.split(",") if r.strip()],
        tags=[t.strip().lower() for t in tags.split(",") if t.strip()], source=f"upload:{actor.username}",
    )
    try:
        doc = container.ingestion.ingest(db, req, tenant_id=actor.tenant_id, actor=actor)
    except DocumentLoadError as exc:
        raise ApiError(422, "invalid_document", str(exc)) from exc
    except DuplicateDocumentError as exc:
        raise ApiError(409, "duplicate_document", "An identical document is already indexed.",
                       details={"existing_document_id": exc.existing_id}) from exc
    except DocumentConflictError as exc:
        raise ApiError(409, "version_conflict", str(exc)) from exc
    db.commit()
    return document_out(doc, container.settings)


@router.post("/search", summary="Authorized hybrid retrieval test with citations and scores")
def search(body: SearchRequest, db: DbDep, container: ContainerDep,
           current: CurrentUser = Depends(require(Permission.KNOWLEDGE_SEARCH))) -> dict[str, Any]:
    try:
        res = container.retriever.search(db, current.actor, body.query, top_k=body.top_k, mode=body.mode,
                                         classifications=tuple(c.value for c in body.classifications),
                                         tags=tuple(body.tags), document_ids=tuple(body.document_ids))
    except RetrievalError as exc:
        db.commit()
        raise ApiError(503, "retrieval_unavailable", f"Retrieval failed ({exc.code}).") from exc
    db.commit()
    return {"query": res.query, "mode": res.mode, "sufficient": res.sufficient, "reason": res.reason,
            "top_score": res.top_score, "excluded_unauthorized": res.excluded_unauthorized,
            "candidate_count": res.candidate_count, "latency_ms": res.latency_ms, "index_version": res.index_version,
            "results": [r.as_dict() for r in res.results]}


@router.post("/documents/{doc_id}/reindex", summary="Re-chunk and re-embed a document with the current index version")
def reindex(doc_id: str, db: DbDep, container: ContainerDep,
            current: CurrentUser = Depends(require(Permission.KNOWLEDGE_MANAGE))) -> dict[str, Any]:
    doc = document_or_404(db, current.actor, doc_id)
    try:
        doc = container.ingestion.reindex(db, doc, actor=current.actor)
    except DocumentConflictError as exc:
        raise ApiError(409, "conflict", str(exc)) from exc
    db.commit()
    return document_out(doc, container.settings)


@router.post("/reindex-stale", summary="Re-index all documents whose index version is stale")
def reindex_stale(db: DbDep, container: ContainerDep,
                  current: CurrentUser = Depends(require(Permission.KNOWLEDGE_MANAGE))) -> dict[str, Any]:
    count = container.ingestion.reindex_stale(db, tenant_id=current.actor.tenant_id, actor=current.actor)
    db.commit()
    return {"reindexed": count, "index_version": container.settings.index_version}


@router.delete("/documents/{doc_id}", summary="Soft-delete a document (chunks purged; text retained until retention)")
def delete_document(doc_id: str, db: DbDep, container: ContainerDep,
                    current: CurrentUser = Depends(require(Permission.KNOWLEDGE_MANAGE))) -> dict[str, Any]:
    doc = document_or_404(db, current.actor, doc_id)
    if doc.deleted_at is not None:
        raise ApiError(409, "already_deleted", "Document is already deleted.")
    container.ingestion.delete(db, doc, actor=current.actor)
    db.commit()
    return document_out(doc, container.settings)
