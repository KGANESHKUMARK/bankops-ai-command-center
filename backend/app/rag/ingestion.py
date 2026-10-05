"""Knowledge ingestion: validate -> extract -> normalize -> neutralize -> chunk -> embed -> index.

Includes duplicate detection (content hash), version supersession, re-indexing
for stale index versions, soft deletion with retention and full status tracking.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.domain import CLASSIFICATION_RANK, Classification, DocumentStatus, Role, roles_to_mask
from app.models import KnowledgeChunk, KnowledgeDocument
from app.policy.engine import Actor
from app.rag.chunking import chunk_document
from app.rag.embeddings import Embedder, EmbeddingError
from app.rag.injection import neutralize
from app.rag.loaders import DocumentLoadError, load_document
from app.rag.text import estimate_tokens
from app.services.audit import record_audit

log = get_logger("rag.ingestion")
_DOC_KEY = re.compile(r"^[A-Z0-9][A-Z0-9\-]{2,63}$")
_VERSION = re.compile(r"^\d+(\.\d+){0,2}$")


class DuplicateDocumentError(Exception):
    def __init__(self, existing_id: str) -> None:
        super().__init__("duplicate document")
        self.existing_id = existing_id


class DocumentConflictError(Exception):
    pass


@dataclass
class IngestRequest:
    filename: str
    data: bytes
    title: str
    doc_key: str
    version: str
    classification: Classification
    allowed_roles: list[str]
    tags: list[str]
    source: str
    is_synthetic: bool = True


class IngestionService:
    def __init__(self, settings: Settings, embedder: Embedder) -> None:
        self.settings = settings
        self.embedder = embedder

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _validate_metadata(req: IngestRequest) -> None:
        if not _DOC_KEY.match(req.doc_key):
            raise DocumentLoadError("doc_key must be 3-64 chars: uppercase letters, digits and dashes.")
        if not _VERSION.match(req.version):
            raise DocumentLoadError("version must look like 1, 1.2 or 1.2.3.")
        if not 3 <= len(req.title.strip()) <= 200:
            raise DocumentLoadError("title must be 3-200 characters.")
        if not req.allowed_roles:
            raise DocumentLoadError("allowed_roles must include at least one role.")
        for role in req.allowed_roles:
            if role not in Role._value2member_map_:
                raise DocumentLoadError(f"Unknown role '{role}'.")
        if len(req.tags) > 12 or any(not re.fullmatch(r"[a-z0-9][a-z0-9\-]{0,40}", t) for t in req.tags):
            raise DocumentLoadError("tags must be lowercase slugs (max 12).")

    def _index(self, db: Session, doc: KnowledgeDocument, text: str) -> None:
        chunks = chunk_document(
            text,
            title=doc.title,
            source_type=doc.source_type,
            chunk_size=self.settings.chunk_size,
            overlap=self.settings.chunk_overlap,
        )
        if not chunks:
            raise DocumentLoadError("Document produced no indexable chunks.")
        vectors = self.embedder.embed([f"{doc.title}\n{c.section}\n{c.content}" for c in chunks])
        rank = CLASSIFICATION_RANK[Classification(doc.classification)]
        flagged = 0
        for chunk, vector in zip(chunks, vectors, strict=True):
            sanitized = neutralize(chunk.content)
            flagged += int(sanitized.detected)
            db.add(
                KnowledgeChunk(
                    document_id=doc.id,
                    tenant_id=doc.tenant_id,
                    chunk_index=chunk.index,
                    section=chunk.section,
                    content=sanitized.text,
                    content_hash=hashlib.sha256(sanitized.text.encode()).hexdigest(),
                    char_count=len(sanitized.text),
                    token_estimate=estimate_tokens(sanitized.text),
                    classification=doc.classification,
                    classification_rank=rank,
                    allowed_roles_mask=doc.allowed_roles_mask,
                    embedding=vector,
                    embedding_model=f"{self.embedder.provider}:{self.embedder.model}",
                    index_version=self.settings.index_version,
                    injection_detected=sanitized.detected,
                    injection_patterns=sanitized.pattern_ids,
                )
            )
        doc.chunk_count = len(chunks)
        doc.injection_flag_count = flagged
        doc.index_version = self.settings.index_version
        doc.status = DocumentStatus.INDEXED.value
        doc.status_detail = (
            f"Indexed {len(chunks)} chunks; {flagged} chunk(s) contained neutralized instruction-like content."
            if flagged
            else f"Indexed {len(chunks)} chunks."
        )

    # ------------------------------------------------------------------- ingest
    def ingest(self, db: Session, req: IngestRequest, *, tenant_id: str, actor: Actor | None) -> KnowledgeDocument:
        self._validate_metadata(req)
        loaded = load_document(req.filename, req.data, max_bytes=self.settings.max_upload_bytes)
        # Neutralize the full text once; the stored text never carries raw injected instructions.
        text = neutralize(loaded.text).text
        content_hash = hashlib.sha256(loaded.text.encode()).hexdigest()

        live = select(KnowledgeDocument).where(
            KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.deleted_at.is_(None)
        )
        dup = db.execute(live.where(KnowledgeDocument.content_hash == content_hash)).scalars().first()
        if dup is not None:
            raise DuplicateDocumentError(dup.id)
        same_version = db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.doc_key == req.doc_key,
                KnowledgeDocument.version == req.version,
            )
        ).scalars().first()
        if same_version is not None:
            raise DocumentConflictError(
                f"{req.doc_key} v{req.version} already exists with different content; bump the version."
            )

        doc = KnowledgeDocument(
            tenant_id=tenant_id,
            doc_key=req.doc_key,
            title=req.title.strip(),
            version=req.version,
            source=req.source[:255],
            source_type=loaded.source_type,
            classification=req.classification.value,
            allowed_roles=sorted(set(req.allowed_roles)),
            allowed_roles_mask=roles_to_mask(req.allowed_roles),
            tags=sorted(set(req.tags)),
            content_hash=content_hash,
            content_text=text,
            byte_size=loaded.byte_size,
            status=DocumentStatus.INDEXING.value,
            uploaded_by=actor.user_id if actor else None,
            is_synthetic=req.is_synthetic,
        )
        db.add(doc)
        db.flush()
        try:
            self._index(db, doc, text)
        except (EmbeddingError, DocumentLoadError, ValueError) as exc:
            db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
            doc.status = DocumentStatus.FAILED.value
            doc.status_detail = f"Indexing failed: {getattr(exc, 'code', type(exc).__name__)}"
            log.warning("ingestion failed", extra={"doc_key": req.doc_key, "error_code": doc.status_detail})
        else:
            self._supersede_older_versions(db, doc)
        record_audit(
            db,
            tenant_id=tenant_id,
            action="knowledge.ingested" if doc.status == DocumentStatus.INDEXED.value else "knowledge.ingest_failed",
            resource_type="knowledge_document",
            resource_id=doc.id,
            outcome="success" if doc.status == DocumentStatus.INDEXED.value else "failure",
            actor=actor,
            details={
                "doc_key": doc.doc_key,
                "version": doc.version,
                "classification": doc.classification,
                "chunks": doc.chunk_count,
                "injection_flags": doc.injection_flag_count,
                "source_type": doc.source_type,
            },
        )
        db.flush()
        return doc

    def _supersede_older_versions(self, db: Session, doc: KnowledgeDocument) -> None:
        older = db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.tenant_id == doc.tenant_id,
                KnowledgeDocument.doc_key == doc.doc_key,
                KnowledgeDocument.id != doc.id,
                KnowledgeDocument.deleted_at.is_(None),
            )
        ).scalars()
        for old in older:
            self._soft_delete(db, old, detail=f"Superseded by version {doc.version}")

    # ---------------------------------------------------------- lifecycle ops
    def _soft_delete(self, db: Session, doc: KnowledgeDocument, *, detail: str) -> None:
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
        now = utcnow()
        doc.status = DocumentStatus.DELETED.value
        doc.status_detail = detail
        doc.deleted_at = now
        doc.retention_until = now + timedelta(days=self.settings.retention_deleted_documents_days)
        doc.chunk_count = 0

    def delete(self, db: Session, doc: KnowledgeDocument, *, actor: Actor) -> None:
        self._soft_delete(db, doc, detail="Deleted by user; chunks purged from the index.")
        record_audit(
            db,
            tenant_id=doc.tenant_id,
            action="knowledge.deleted",
            resource_type="knowledge_document",
            resource_id=doc.id,
            actor=actor,
            details={"doc_key": doc.doc_key, "version": doc.version, "retention_until": str(doc.retention_until)},
        )

    def reindex(self, db: Session, doc: KnowledgeDocument, *, actor: Actor | None) -> KnowledgeDocument:
        if doc.deleted_at is not None or not doc.content_text:
            raise DocumentConflictError("Deleted documents cannot be re-indexed.")
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
        doc.status = DocumentStatus.INDEXING.value
        db.flush()
        try:
            self._index(db, doc, doc.content_text)
        except (EmbeddingError, DocumentLoadError, ValueError) as exc:
            doc.status = DocumentStatus.FAILED.value
            doc.status_detail = f"Re-index failed: {getattr(exc, 'code', type(exc).__name__)}"
        record_audit(
            db,
            tenant_id=doc.tenant_id,
            action="knowledge.reindexed",
            resource_type="knowledge_document",
            resource_id=doc.id,
            outcome="success" if doc.status == DocumentStatus.INDEXED.value else "failure",
            actor=actor,
            details={"doc_key": doc.doc_key, "index_version": doc.index_version, "chunks": doc.chunk_count},
        )
        db.flush()
        return doc

    def reindex_stale(self, db: Session, *, tenant_id: str | None = None, actor: Actor | None = None) -> int:
        query = select(KnowledgeDocument).where(
            KnowledgeDocument.deleted_at.is_(None),
            (KnowledgeDocument.index_version != self.settings.index_version)
            | (KnowledgeDocument.index_version.is_(None))
            | (KnowledgeDocument.status == DocumentStatus.FAILED.value),
        )
        if tenant_id:
            query = query.where(KnowledgeDocument.tenant_id == tenant_id)
        count = 0
        for doc in db.execute(query).scalars().all():
            self.reindex(db, doc, actor=actor)
            count += 1
        return count
