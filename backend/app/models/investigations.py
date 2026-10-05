from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_id, utcnow
from app.db.types import UTCDateTime
from app.domain import InvestigationStatus, sql_in
from app.models._common import JSONType


class InvestigationRun(Base):
    __tablename__ = "investigation_runs"
    __table_args__ = (
        CheckConstraint(f"status IN ({sql_in(InvestigationStatus)})", name="valid_status"),
        CheckConstraint("execution_mode IN ('live', 'dry_run')", name="valid_execution_mode"),
        CheckConstraint("step_count >= 0 AND tool_call_count >= 0", name="non_negative_counters"),
        Index("ix_investigation_runs_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(24), default=InvestigationStatus.QUEUED.value)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phase: Mapped[str] = mapped_column(String(32), default="analysis")
    current_node: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    model_mode: Mapped[str] = mapped_column(String(16))
    prompt_versions: Mapped[dict[str, str]] = mapped_column(JSONType, default=dict)
    workflow_version: Mapped[str] = mapped_column(String(32))
    index_version: Mapped[str] = mapped_column(String(32))
    policy_version: Mapped[str] = mapped_column(String(32))
    state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_evaluation: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(16), default="live")
    lock_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_seq: Mapped[int] = mapped_column(Integer, default=0)


class InvestigationEvent(Base):
    __tablename__ = "investigation_events"
    __table_args__ = (UniqueConstraint("investigation_id", "seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    event_type: Mapped[str] = mapped_column(String(40))
    agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'error', 'denied', 'rejected', 'timeout')", name="valid_status"),
        Index("ix_tool_calls_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64))
    investigation_id: Mapped[str | None] = mapped_column(
        ForeignKey("investigation_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(80))
    agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    args: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    requested_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class LLMCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'error', 'skipped')", name="valid_status"),
        Index("ix_llm_calls_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64))
    investigation_id: Mapped[str | None] = mapped_column(
        ForeignKey("investigation_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    agent: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    prompt_id: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    tokens_estimated: Mapped[bool] = mapped_column(Boolean, default=True)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (UniqueConstraint("investigation_id", "label"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(8))
    kind: Mapped[str] = mapped_column(String(32))
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"), nullable=True
    )
    chunk_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_chunks.id", ondelete="SET NULL"), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    section: Mapped[str | None] = mapped_column(String(500), nullable=True)
    chunk_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification: Mapped[str | None] = mapped_column(String(16), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    excerpt: Mapped[str] = mapped_column(Text)
    injection_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class RetrievalLog(Base):
    __tablename__ = "retrieval_logs"
    __table_args__ = (Index("ix_retrieval_logs_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    investigation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    query_preview: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(16))
    top_k: Mapped[int] = mapped_column(Integer)
    result_count: Mapped[int] = mapped_column(Integer)
    excluded_unauthorized: Mapped[int] = mapped_column(Integer, default=0)
    top_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    sufficient: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
