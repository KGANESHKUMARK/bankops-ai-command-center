from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.db.base import Base, new_id, utcnow
from app.db.types import EmbeddingVector, UTCDateTime
from app.domain import Classification, DocumentStatus, sql_in
from app.models._common import JSONType


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "doc_key", "version"),
        CheckConstraint(f"classification IN ({sql_in(Classification)})", name="valid_classification"),
        CheckConstraint(f"status IN ({sql_in(DocumentStatus)})", name="valid_status"),
        CheckConstraint("source_type IN ('markdown', 'text', 'pdf')", name="valid_source_type"),
        Index("ix_knowledge_documents_tenant_hash", "tenant_id", "content_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    doc_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(16))
    classification: Mapped[str] = mapped_column(String(16))
    allowed_roles: Mapped[list[str]] = mapped_column(JSONType, default=list)
    allowed_roles_mask: Mapped[int] = mapped_column(Integer)
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    content_hash: Mapped[str] = mapped_column(String(64))
    # Normalized, injection-neutralized text retained for re-indexing (purged by retention).
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default=DocumentStatus.PENDING.value)
    status_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    injection_flag_count: Mapped[int] = mapped_column(Integer, default=0)
    index_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    retention_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        Index("ix_knowledge_chunks_tenant_rank", "tenant_id", "classification_rank"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    chunk_index: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    char_count: Mapped[int] = mapped_column(Integer)
    token_estimate: Mapped[int] = mapped_column(Integer)
    classification: Mapped[str] = mapped_column(String(16))
    classification_rank: Mapped[int] = mapped_column(Integer)
    allowed_roles_mask: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVector(get_settings().embedding_dim))
    embedding_model: Mapped[str] = mapped_column(String(100))
    index_version: Mapped[str] = mapped_column(String(32))
    injection_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    injection_patterns: Mapped[list[str]] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
