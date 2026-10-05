from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_id, utcnow
from app.db.types import UTCDateTime
from app.models._common import JSONType


class AuditEvent(Base):
    """Append-only, hash-chained audit stream.

    Intentionally has no foreign keys so audit history survives deletion of the
    records it describes (e.g. demo resets). Updates/deletes are blocked by an ORM
    guard (see app.services.audit) and each row stores the hash of its predecessor.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("outcome IN ('success', 'denied', 'failure', 'info')", name="valid_outcome"),
        Index("ix_audit_events_tenant_time", "tenant_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    resource_type: Mapped[str] = mapped_column(String(48))
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16))
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    investigation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class PolicyDecisionRecord(Base):
    __tablename__ = "policy_decisions"
    __table_args__ = (
        CheckConstraint("decision IN ('allow', 'deny', 'require_approval')", name="valid_decision"),
        Index("ix_policy_decisions_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64))
    investigation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    subject_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    subject_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action_name: Mapped[str] = mapped_column(String(80))
    resource: Mapped[str | None] = mapped_column(String(100), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16))
    decision: Mapped[str] = mapped_column(String(24))
    rule_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    explanation: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("prompt_id", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    prompt_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(16))
    template_hash: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ModelConfigVersion(Base):
    __tablename__ = "model_config_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    config_hash: Mapped[str] = mapped_column(String(64), unique=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    embedding_provider: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(100))
    embedding_dim: Mapped[int] = mapped_column(Integer)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ReleasePromotion(Base):
    """Simulated promotion of a versioned AI configuration bundle between environments."""

    __tablename__ = "release_promotions"
    __table_args__ = (
        CheckConstraint("to_env IN ('development', 'staging', 'production_ready')", name="valid_to_env"),
        CheckConstraint("status IN ('promoted', 'blocked', 'rolled_back')", name="valid_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64))
    bundle_hash: Mapped[str] = mapped_column(String(64))
    components: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    from_env: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_env: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16))
    evaluation_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="SET NULL"), nullable=True
    )
    gate_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    gate_failures: Mapped[list[str]] = mapped_column(JSONType, default=list)
    promoted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    previous_promotion_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    rollback_of_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class DemoFlag(Base):
    """Runtime demo flags (failure injection). Stored in the DB so all workers agree."""

    __tablename__ = "demo_flags"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
