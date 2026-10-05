from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_id, utcnow
from app.db.types import UTCDateTime
from app.domain import ActionStatus, ApprovalStatus, RiskLevel, VerificationStatus, sql_in
from app.models._common import JSONType


class ActionRecord(Base):
    """A proposed or executed *simulated* remediation action.

    Execution is only possible from `approved` / `approved_by_policy` states and is
    guarded by a unique idempotency key plus an atomic compare-and-set on status.
    """

    __tablename__ = "action_records"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        CheckConstraint(f"status IN ({sql_in(ActionStatus)})", name="valid_status"),
        CheckConstraint(f"risk_level IN ({sql_in(RiskLevel)})", name="valid_risk"),
        CheckConstraint(f"verification_status IN ({sql_in(VerificationStatus)})", name="valid_verification"),
        CheckConstraint(
            "risk_level != 'prohibited' OR status IN ('denied', 'invalidated')", name="prohibited_never_executable"
        ),
        Index("ix_action_records_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    investigation_id: Mapped[str | None] = mapped_column(
        ForeignKey("investigation_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    tool_name: Mapped[str] = mapped_column(String(80))
    target_resource: Mapped[str] = mapped_column(String(100))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    action_hash: Mapped[str] = mapped_column(String(64))
    risk_level: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    policy_decision: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    preconditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    state_before: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(24), default=VerificationStatus.NOT_VERIFIED.value)
    verification_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    rollback_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    rollback_status: Mapped[str] = mapped_column(String(24), default="not_applicable")
    rollback_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_version: Mapped[int] = mapped_column(Integer, default=1)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_effect: Mapped[str | None] = mapped_column(Text, nullable=True)
    depends_on_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Approval(Base):
    """Human approval bound to one specific action hash (plan change => invalid)."""

    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("action_id"),
        CheckConstraint(f"status IN ({sql_in(ApprovalStatus)})", name="valid_status"),
        # Separation of duties enforced at the database layer as a last line of defense.
        CheckConstraint(
            "status != 'approved' OR risk_level != 'high' OR decided_by IS NULL OR decided_by != requested_by",
            name="no_self_approval_high_risk",
        ),
        Index("ix_approvals_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    action_id: Mapped[str] = mapped_column(ForeignKey("action_records.id", ondelete="CASCADE"))
    investigation_id: Mapped[str | None] = mapped_column(
        ForeignKey("investigation_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    required_roles: Mapped[list[str]] = mapped_column(JSONType, default=list)
    risk_level: Mapped[str] = mapped_column(String(16))
    action_hash: Mapped[str] = mapped_column(String(64))
    target_resource: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default=ApprovalStatus.PENDING.value)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
