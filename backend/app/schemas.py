"""API request/response contracts. Requests forbid unknown fields (mass-assignment defense)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.domain import ApprovalReason, CancellationReason, Classification, RejectionReason

T = TypeVar("T")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# ------------------------------------------------------------------- auth
class LoginRequest(StrictModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9._@\-]+$")
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    email: str
    role: str
    tenant_id: str
    tenant_name: str
    permissions: list[str]
    is_demo_account: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    expires_at: datetime
    user: UserOut


# -------------------------------------------------------------- incidents
class IncidentSummary(BaseModel):
    id: str
    number: str
    title: str
    category: str
    severity: str
    status: str
    classification: str
    primary_service: str | None
    affected_services: list[str]
    owner_team: str
    detected_at: datetime
    updated_at: datetime
    scenario_key: str | None
    is_synthetic: bool


class StartInvestigationRequest(StrictModel):
    notes: str | None = Field(default=None, max_length=1000)


# --------------------------------------------------------------- approvals
class ApproveRequest(StrictModel):
    confirm: Literal[True] = Field(description="Must be true: explicit human confirmation of the simulated action.")
    reason_code: ApprovalReason = ApprovalReason.EVIDENCE_SUFFICIENT
    comment: str | None = Field(default=None, max_length=1000)


class RejectRequest(StrictModel):
    reason_code: RejectionReason
    comment: str | None = Field(default=None, max_length=1000)


class CancelRequest(StrictModel):
    reason_code: CancellationReason
    comment: str | None = Field(default=None, max_length=1000)


class RollbackRequest(StrictModel):
    confirm: Literal[True]
    reason: str = Field(min_length=3, max_length=300)


class CancelInvestigationRequest(StrictModel):
    reason: str = Field(default="Cancelled by user", min_length=3, max_length=300)


# --------------------------------------------------------------- knowledge
class SearchRequest(StrictModel):
    query: str = Field(min_length=3, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid"
    classifications: list[Classification] = Field(default_factory=list, max_length=4)
    tags: list[str] = Field(default_factory=list, max_length=8)
    document_ids: list[str] = Field(default_factory=list, max_length=20)


class DocumentOut(BaseModel):
    id: str
    doc_key: str
    title: str
    version: str
    source: str
    source_type: str
    classification: str
    allowed_roles: list[str]
    tags: list[str]
    status: str
    status_detail: str | None
    chunk_count: int
    injection_flag_count: int
    index_version: str | None
    index_current: bool
    content_hash: str
    byte_size: int
    is_synthetic: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    retention_until: datetime | None


# -------------------------------------------------------------- governance
class PromotionRequest(StrictModel):
    to_env: Literal["development", "staging", "production_ready"]
    evaluation_run_id: str = Field(min_length=36, max_length=36)
    notes: str | None = Field(default=None, max_length=500)


class PromotionRollbackRequest(StrictModel):
    reason: str = Field(min_length=3, max_length=300)


class RetentionApplyRequest(StrictModel):
    dry_run: bool = True


class EvaluationRunRequest(StrictModel):
    include_workflow: bool = True
    notes: str | None = Field(default=None, max_length=300)


class FaultRequest(StrictModel):
    enabled: bool


class HealthOut(BaseModel):
    status: str
    version: str
    environment: str
    synthetic_data: bool = True


class GenericMessage(BaseModel):
    message: str
    details: dict[str, Any] | None = None
