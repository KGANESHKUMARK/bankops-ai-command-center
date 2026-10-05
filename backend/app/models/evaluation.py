from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_id, utcnow
from app.db.types import UTCDateTime
from app.models._common import JSONType


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (CheckConstraint("status IN ('running', 'completed', 'failed')", name="valid_status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    triggered_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    dataset_id: Mapped[str] = mapped_column(String(64))
    dataset_version: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    model_mode: Mapped[str] = mapped_column(String(16))
    prompt_versions: Mapped[dict[str, str]] = mapped_column(JSONType, default=dict)
    retrieval_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    index_version: Mapped[str] = mapped_column(String(32))
    workflow_version: Mapped[str] = mapped_column(String(32))
    policy_version: Mapped[str] = mapped_column(String(32))
    bundle_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    gate_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gate_failures: Mapped[list[str]] = mapped_column(JSONType, default=list)
    is_model_assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    judge_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class EvaluationCaseResult(Base):
    __tablename__ = "evaluation_case_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(String(64))
    case_type: Mapped[str] = mapped_column(String(32))
    passed: Mapped[bool] = mapped_column(Boolean)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
