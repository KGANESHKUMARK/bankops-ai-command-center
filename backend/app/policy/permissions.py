"""Role-based access control matrix (single source of truth, enforced server-side)."""

from __future__ import annotations

from enum import StrEnum

from app.domain import Role


class Permission(StrEnum):
    DASHBOARD_READ = "dashboard:read"
    INCIDENTS_READ = "incidents:read"
    INVESTIGATIONS_READ = "investigations:read"
    INVESTIGATIONS_START = "investigations:start"
    INVESTIGATIONS_RESUME = "investigations:resume"
    DIAGNOSTICS_RUN = "diagnostics:run"
    ACTIONS_READ = "actions:read"
    ACTIONS_REQUEST = "actions:request"
    ACTIONS_VERIFY = "actions:verify"
    ACTIONS_ROLLBACK = "actions:rollback"
    APPROVALS_READ = "approvals:read"
    APPROVALS_DECIDE = "approvals:decide"
    APPROVALS_CANCEL = "approvals:cancel"
    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_SEARCH = "knowledge:search"
    KNOWLEDGE_INGEST = "knowledge:ingest"
    KNOWLEDGE_MANAGE = "knowledge:manage"
    GOVERNANCE_READ = "governance:read"
    AUDIT_READ = "audit:read"
    USERS_READ = "users:read"
    EVALUATIONS_READ = "evaluations:read"
    EVALUATIONS_RUN = "evaluations:run"
    PROMOTIONS_MANAGE = "promotions:manage"
    RETENTION_MANAGE = "retention:manage"
    OBSERVABILITY_READ = "observability:read"
    SETTINGS_READ = "settings:read"
    DEMO_RESET = "demo:reset"
    DEMO_FAULTS = "demo:faults"


P = Permission

_ANALYST = {
    P.DASHBOARD_READ,
    P.INCIDENTS_READ,
    P.INVESTIGATIONS_READ,
    P.INVESTIGATIONS_START,
    P.INVESTIGATIONS_RESUME,
    P.DIAGNOSTICS_RUN,
    P.ACTIONS_READ,
    P.ACTIONS_REQUEST,
    P.ACTIONS_VERIFY,
    P.APPROVALS_READ,
    P.APPROVALS_CANCEL,
    P.KNOWLEDGE_READ,
    P.KNOWLEDGE_SEARCH,
    P.EVALUATIONS_READ,
    P.OBSERVABILITY_READ,
    P.SETTINGS_READ,
}

_MANAGER = _ANALYST | {
    P.APPROVALS_DECIDE,
    P.ACTIONS_ROLLBACK,
    P.KNOWLEDGE_INGEST,
    P.KNOWLEDGE_MANAGE,
    P.GOVERNANCE_READ,
    P.AUDIT_READ,
    P.USERS_READ,
    P.EVALUATIONS_RUN,
    P.PROMOTIONS_MANAGE,
}

_AUDITOR = {
    P.DASHBOARD_READ,
    P.INCIDENTS_READ,
    P.INVESTIGATIONS_READ,
    P.ACTIONS_READ,
    P.APPROVALS_READ,
    P.KNOWLEDGE_READ,
    P.KNOWLEDGE_SEARCH,
    P.GOVERNANCE_READ,
    P.AUDIT_READ,
    P.USERS_READ,
    P.EVALUATIONS_READ,
    P.OBSERVABILITY_READ,
    P.SETTINGS_READ,
}

_READ_ONLY = {
    P.DASHBOARD_READ,
    P.INCIDENTS_READ,
    P.INVESTIGATIONS_READ,
    P.ACTIONS_READ,
    P.APPROVALS_READ,
    P.KNOWLEDGE_READ,
    P.KNOWLEDGE_SEARCH,
    P.SETTINGS_READ,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.DEMO_ADMIN: frozenset(set(Permission)),
    Role.OPERATIONS_MANAGER: frozenset(_MANAGER),
    Role.OPERATIONS_ANALYST: frozenset(_ANALYST),
    Role.AUDITOR: frozenset(_AUDITOR),
    Role.READ_ONLY: frozenset(_READ_ONLY),
}

ROLE_DESCRIPTIONS: dict[Role, str] = {
    Role.DEMO_ADMIN: "Demo administrator: full access incl. demo reset and failure injection (local/demo only). "
    "May approve medium-risk actions only.",
    Role.OPERATIONS_MANAGER: "Approves medium/high-risk simulated actions (never their own high-risk requests), "
    "manages knowledge and promotions.",
    Role.OPERATIONS_ANALYST: "Runs investigations and read-only diagnostics; requests simulated remediation.",
    Role.AUDITOR: "Read-only access to incidents, approvals, actions, audit log and governance; cannot act.",
    Role.READ_ONLY: "Read-only access to non-restricted incidents and internal/public knowledge.",
}


def has_permission(role: str, permission: Permission) -> bool:
    try:
        return permission in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False


def permissions_for(role: str) -> list[str]:
    try:
        return sorted(p.value for p in ROLE_PERMISSIONS[Role(role)])
    except ValueError:
        return []
