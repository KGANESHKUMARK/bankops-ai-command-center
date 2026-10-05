"""Domain vocabulary shared by models, policy engine, API schemas and the workflow."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    DEMO_ADMIN = "demo_admin"
    OPERATIONS_ANALYST = "operations_analyst"
    OPERATIONS_MANAGER = "operations_manager"
    AUDITOR = "auditor"
    READ_ONLY = "read_only"


ROLE_BITS: dict[Role, int] = {
    Role.DEMO_ADMIN: 1,
    Role.OPERATIONS_ANALYST: 2,
    Role.OPERATIONS_MANAGER: 4,
    Role.AUDITOR: 8,
    Role.READ_ONLY: 16,
}


def roles_to_mask(roles: list[str] | tuple[str, ...] | set[str]) -> int:
    mask = 0
    for role in roles:
        mask |= ROLE_BITS[Role(role)]
    return mask


class Classification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


CLASSIFICATION_RANK: dict[Classification, int] = {
    Classification.PUBLIC: 0,
    Classification.INTERNAL: 1,
    Classification.CONFIDENTIAL: 2,
    Classification.RESTRICTED: 3,
}

# Highest data classification each role may read (enforced server-side in SQL + Python).
ROLE_CLEARANCE: dict[Role, Classification] = {
    Role.READ_ONLY: Classification.INTERNAL,
    Role.OPERATIONS_ANALYST: Classification.CONFIDENTIAL,
    Role.OPERATIONS_MANAGER: Classification.RESTRICTED,
    Role.AUDITOR: Classification.RESTRICTED,
    Role.DEMO_ADMIN: Classification.RESTRICTED,
}


def clearance_rank(role: str) -> int:
    return CLASSIFICATION_RANK[ROLE_CLEARANCE[Role(role)]]


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IncidentStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    AWAITING_APPROVAL = "awaiting_approval"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class ServiceStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class RiskLevel(StrEnum):
    READ_ONLY = "read_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    PROHIBITED = "prohibited"


RISK_ORDER = [RiskLevel.READ_ONLY, RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.PROHIBITED]


class InvestigationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


TERMINAL_INVESTIGATION_STATUSES = {
    InvestigationStatus.COMPLETED,
    InvestigationStatus.FAILED,
    InvestigationStatus.CANCELLED,
}


class InvestigationOutcome(StrEnum):
    RESOLVED = "resolved"
    PARTIALLY_RESOLVED = "partially_resolved"
    UNRESOLVED = "unresolved"
    NO_ACTION_TAKEN = "no_action_taken"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    ABORTED = "aborted"
    DRY_RUN = "dry_run"


class ActionStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    APPROVED_BY_POLICY = "approved_by_policy"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    DENIED = "denied"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


EXECUTABLE_ACTION_STATUSES = {ActionStatus.APPROVED, ActionStatus.APPROVED_BY_POLICY}


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


class VerificationStatus(StrEnum):
    NOT_VERIFIED = "not_verified"
    RESOLVED = "resolved"
    PARTIALLY_RESOLVED = "partially_resolved"
    UNRESOLVED = "unresolved"
    ERROR = "error"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"
    DELETED = "deleted"


class ApprovalReason(StrEnum):
    EVIDENCE_SUFFICIENT = "EVIDENCE_SUFFICIENT"
    APPROVED_WITH_MONITORING = "APPROVED_WITH_MONITORING"


class RejectionReason(StrEnum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    RISK_TOO_HIGH = "RISK_TOO_HIGH"
    CHANGE_FREEZE = "CHANGE_FREEZE"
    ALTERNATIVE_PREFERRED = "ALTERNATIVE_PREFERRED"
    OTHER = "OTHER"


class CancellationReason(StrEnum):
    NO_LONGER_NEEDED = "NO_LONGER_NEEDED"
    PLAN_CHANGED = "PLAN_CHANGED"
    OTHER = "OTHER"


def sql_in(values: list[str] | type[StrEnum]) -> str:
    """Render a SQL IN-list for CHECK constraints from trusted enum values."""
    items = [v.value for v in values] if isinstance(values, type) else list(values)  # type: ignore[union-attr]
    return ", ".join(f"'{v}'" for v in items)
