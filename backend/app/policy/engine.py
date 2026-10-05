"""Deterministic policy engine.

This module is the authorization boundary for AI-proposed actions. It contains no
LLM calls and has no dependency on model availability. Every decision carries
rule IDs and a human-readable explanation, and is recorded in the audit stream by
callers (see app.services.policy_records).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.domain import (
    CLASSIFICATION_RANK,
    ActionStatus,
    ApprovalStatus,
    Classification,
    IncidentStatus,
    RiskLevel,
    Role,
    clearance_rank,
)
from app.policy.catalog import ACTION_CATALOG, PROHIBITED_ACTIONS
from app.policy.permissions import Permission, has_permission

POLICY_VERSION = "policy-2026.09.1"

Decision = Literal["allow", "deny", "require_approval"]


@dataclass(frozen=True)
class Actor:
    user_id: str
    username: str
    role: str
    tenant_id: str


class PolicyDecision(BaseModel):
    decision: Decision
    risk_level: RiskLevel
    rule_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    explanation: str
    required_approver_roles: list[str] = Field(default_factory=list)
    policy_version: str = POLICY_VERSION

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


# Rule catalog (documented in docs/RBAC_AND_POLICY.md and exposed at /governance/policies).
POLICY_RULES: dict[str, str] = {
    "P-001": "Unknown tools (not in the allowlisted registry) are denied.",
    "P-002": "Prohibited actions are never executable, regardless of role, approval or model output.",
    "P-003": "The requester's role must hold the permission required for the action class.",
    "P-004": "Actor, incident and resource must belong to the same tenant.",
    "P-005": "Mutating actions may only target resources on the tool's target allowlist.",
    "P-006": "Read-only diagnostics are allowed for authorized roles.",
    "P-007": "Low-risk simulated actions are allowed without approval (configurable).",
    "P-008": "Medium-risk simulated actions require approval by operations_manager or demo_admin (configurable).",
    "P-009": "High-risk simulated actions always require approval by an operations_manager who is not the requester.",
    "P-010": "No mutating actions on closed or resolved incidents.",
    "P-011": "Actor must have clearance for the incident's data classification.",
    "A-001": "Approver must hold the approvals:decide permission.",
    "A-002": "Approver role must be one of the approval's required roles.",
    "A-003": "Only pending approvals can be decided (no duplicate or stale decisions).",
    "A-004": "Expired approvals cannot be approved.",
    "A-005": "Requesters cannot approve their own high-risk actions (separation of duties); "
    "self-approval of medium-risk actions is disabled by default.",
    "A-006": "Approval is bound to the action hash, incident and target; any plan change invalidates it.",
    "A-007": "Approver and approval must belong to the same tenant.",
    "A-008": "The action must still be awaiting approval.",
    "E-001": "Execution requires status approved or approved_by_policy and a valid, matching approval when required.",
}


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_action_hash(
    *,
    tool_name: str,
    target_resource: str,
    parameters: dict[str, Any],
    incident_id: str,
    investigation_id: str | None,
    plan_version: int,
    step_index: int,
) -> str:
    payload = {
        "tool": tool_name,
        "target": target_resource,
        "params": parameters,
        "incident": incident_id,
        "investigation": investigation_id,
        "plan_version": plan_version,
        "step": step_index,
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def action_hash_of(action: Any) -> str:
    """Recompute the hash of a persisted ActionRecord from its *current* fields."""
    return compute_action_hash(
        tool_name=action.tool_name,
        target_resource=action.target_resource,
        parameters=action.parameters or {},
        incident_id=action.incident_id,
        investigation_id=action.investigation_id,
        plan_version=action.plan_version,
        step_index=action.step_index,
    )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class PolicyEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _deny(risk: RiskLevel, rule: str, reason: str) -> PolicyDecision:
        return PolicyDecision(
            decision="deny", risk_level=risk, rule_ids=[rule], reasons=[reason], explanation=f"DENIED ({rule}): {reason}"
        )

    # --------------------------------------------------------------- data access
    @staticmethod
    def can_read_classification(role: str, classification: str) -> bool:
        return CLASSIFICATION_RANK[Classification(classification)] <= clearance_rank(role)

    @staticmethod
    def can_read_document(actor: Actor, *, tenant_id: str, classification: str, allowed_roles: list[str]) -> bool:
        return (
            tenant_id == actor.tenant_id
            and PolicyEngine.can_read_classification(actor.role, classification)
            and actor.role in allowed_roles
        )

    # ------------------------------------------------------------------ actions
    def evaluate_action(
        self,
        actor: Actor,
        *,
        tool_name: str,
        target_resource: str | None,
        incident_tenant_id: str | None,
        incident_status: str | None,
        incident_classification: str | None = None,
    ) -> PolicyDecision:
        if tool_name in PROHIBITED_ACTIONS:
            return self._deny(
                RiskLevel.PROHIBITED,
                "P-002",
                f"'{tool_name}' is prohibited ({PROHIBITED_ACTIONS[tool_name]}). "
                "Prohibited actions are never executable, regardless of role, approval or model output.",
            )
        policy = ACTION_CATALOG.get(tool_name)
        if policy is None:
            return self._deny(
                RiskLevel.PROHIBITED, "P-001", f"'{tool_name}' is not in the allowlisted tool registry."
            )
        risk = policy.risk
        if incident_tenant_id is not None and incident_tenant_id != actor.tenant_id:
            return self._deny(risk, "P-004", "Tenant mismatch between actor and incident.")
        if incident_classification and not self.can_read_classification(actor.role, incident_classification):
            return self._deny(risk, "P-011", "Actor lacks clearance for the incident's data classification.")

        if risk == RiskLevel.READ_ONLY:
            if not has_permission(actor.role, Permission.DIAGNOSTICS_RUN) and not has_permission(
                actor.role, Permission.ACTIONS_VERIFY
            ):
                return self._deny(risk, "P-003", f"Role '{actor.role}' may not run diagnostics.")
            return PolicyDecision(
                decision="allow",
                risk_level=risk,
                rule_ids=["P-006"],
                reasons=["Read-only diagnostic."],
                explanation="ALLOWED (P-006): read-only diagnostic for an authorized role; no state is modified.",
            )

        if not has_permission(actor.role, Permission.ACTIONS_REQUEST):
            return self._deny(risk, "P-003", f"Role '{actor.role}' may not request remediation actions.")
        if target_resource not in policy.allowed_targets:
            return self._deny(
                risk,
                "P-005",
                f"Target '{target_resource}' is not on the allowlist for {tool_name} "
                f"(allowed: {', '.join(policy.allowed_targets)}).",
            )
        if incident_status in (IncidentStatus.CLOSED, IncidentStatus.RESOLVED):
            return self._deny(risk, "P-010", f"Incident is {incident_status}; mutating actions are not permitted.")

        approvers = [r.value for r in policy.approver_roles]
        if risk == RiskLevel.LOW:
            if self.settings.low_risk_requires_approval:
                return PolicyDecision(
                    decision="require_approval",
                    risk_level=risk,
                    rule_ids=["P-007"],
                    reasons=["Low-risk approval is enabled by configuration."],
                    explanation="APPROVAL REQUIRED (P-007): low-risk approval is enabled by configuration.",
                    required_approver_roles=approvers,
                )
            return PolicyDecision(
                decision="allow",
                risk_level=risk,
                rule_ids=["P-007"],
                reasons=["Low-risk, idempotent simulated action."],
                explanation="ALLOWED (P-007): low-risk simulated action; executes without approval but is audited "
                "and still subject to preconditions.",
            )
        if risk == RiskLevel.MEDIUM:
            if not self.settings.medium_risk_requires_approval:
                return PolicyDecision(
                    decision="allow",
                    risk_level=risk,
                    rule_ids=["P-008"],
                    reasons=["Medium-risk approval disabled by configuration."],
                    explanation="ALLOWED (P-008): medium-risk approval requirement is disabled by configuration.",
                )
            return PolicyDecision(
                decision="require_approval",
                risk_level=risk,
                rule_ids=["P-008"],
                reasons=["Medium-risk simulated action affecting service availability."],
                explanation="APPROVAL REQUIRED (P-008): medium-risk action; an operations_manager or demo_admin "
                "must explicitly approve before simulated execution.",
                required_approver_roles=approvers,
            )
        return PolicyDecision(
            decision="require_approval",
            risk_level=risk,
            rule_ids=["P-009", "A-005"],
            reasons=["High-risk simulated action."],
            explanation="APPROVAL REQUIRED (P-009): high-risk action; requires explicit approval by an "
            "operations_manager who is not the requester (separation of duties).",
            required_approver_roles=approvers,
        )

    # ---------------------------------------------------------------- approvals
    def evaluate_approval(
        self,
        approver: Actor,
        *,
        approval: Any,
        action: Any,
        decision: Literal["approve", "reject"],
        now: datetime | None = None,
    ) -> PolicyDecision:
        now = now or datetime.now(UTC)
        risk = RiskLevel(approval.risk_level)
        if approval.tenant_id != approver.tenant_id or action.tenant_id != approver.tenant_id:
            return self._deny(risk, "A-007", "Approval belongs to a different tenant.")
        if not has_permission(approver.role, Permission.APPROVALS_DECIDE):
            return self._deny(risk, "A-001", f"Role '{approver.role}' may not decide approvals.")
        if approval.status != ApprovalStatus.PENDING:
            return self._deny(risk, "A-003", f"Approval is already {approval.status}; decisions are final.")
        if _as_utc(approval.expires_at) <= now:
            return self._deny(risk, "A-004", "Approval request has expired; the investigation must re-plan.")
        if action.status != ActionStatus.PENDING_APPROVAL:
            return self._deny(risk, "A-008", f"Action is {action.status}, not awaiting approval.")
        if decision == "reject":
            return PolicyDecision(
                decision="allow",
                risk_level=risk,
                rule_ids=["A-001", "A-003"],
                reasons=["Authorized approver rejecting a pending request."],
                explanation="ALLOWED: an authorized approver may reject a pending request.",
            )
        if approver.role not in (approval.required_roles or []):
            return self._deny(
                risk,
                "A-002",
                f"Role '{approver.role}' is not an approver for {risk} actions "
                f"(required: {', '.join(approval.required_roles or [])}).",
            )
        is_self = approver.user_id == approval.requested_by
        if is_self and (risk == RiskLevel.HIGH or not self.settings.allow_self_approval_medium):
            return self._deny(
                risk, "A-005", "Separation of duties: the requester cannot approve their own action request."
            )
        if action_hash_of(action) != approval.action_hash or action.action_hash != approval.action_hash:
            return self._deny(
                risk, "A-006", "The action changed after approval was requested (hash mismatch); approval invalid."
            )
        if action.incident_id != approval.incident_id or action.target_resource != approval.target_resource:
            return self._deny(risk, "A-006", "Approval scope (incident/target) does not match the action.")
        return PolicyDecision(
            decision="allow",
            risk_level=risk,
            rule_ids=["A-001", "A-002", "A-003", "A-004", "A-005", "A-006", "A-007", "A-008"],
            reasons=["All approval checks passed."],
            explanation=f"ALLOWED: {approver.role} '{approver.username}' may approve this {risk} action; scope, "
            "expiry, hash and separation-of-duties checks passed.",
        )

    # ---------------------------------------------------------------- execution
    def evaluate_execution(self, *, action: Any, approval: Any | None, now: datetime | None = None) -> PolicyDecision:
        """Defense-in-depth re-check immediately before a simulated action executes."""
        now = now or datetime.now(UTC)
        risk = RiskLevel(action.risk_level) if action.risk_level in RiskLevel._value2member_map_ else RiskLevel.PROHIBITED
        if action.tool_name in PROHIBITED_ACTIONS or action.tool_name not in ACTION_CATALOG:
            return self._deny(RiskLevel.PROHIBITED, "P-002", "Prohibited or unknown actions are never executable.")
        if ACTION_CATALOG[action.tool_name].risk != risk:
            return self._deny(risk, "E-001", "Recorded risk level does not match the catalog; refusing to execute.")
        # The caller has already performed an atomic approved -> executing transition (idempotency guard);
        # EXECUTING is therefore the expected status at this point.
        if action.status not in (ActionStatus.APPROVED, ActionStatus.APPROVED_BY_POLICY, ActionStatus.EXECUTING):
            return self._deny(risk, "E-001", f"Action status is {action.status}; execution requires approval.")
        if action.action_hash != action_hash_of(action):
            return self._deny(risk, "A-006", "Action parameters changed after the policy decision; refusing.")
        if action.requires_approval:
            if approval is None or approval.status != ApprovalStatus.APPROVED:
                return self._deny(risk, "E-001", "A valid approval is required but missing.")
            if approval.action_hash != action.action_hash:
                return self._deny(risk, "A-006", "Approval does not match the current action hash.")
            if risk == RiskLevel.HIGH and approval.decided_by == action.requested_by:
                return self._deny(risk, "A-005", "Self-approved high-risk action; refusing to execute.")
        elif risk in (RiskLevel.MEDIUM, RiskLevel.HIGH) and (
            risk == RiskLevel.HIGH or self.settings.medium_risk_requires_approval
        ):
            return self._deny(risk, "E-001", f"{risk} action recorded without approval requirement; refusing.")
        return PolicyDecision(
            decision="allow",
            risk_level=risk,
            rule_ids=["E-001"],
            reasons=["Execution preconditions satisfied."],
            explanation="ALLOWED (E-001): status, hash and approval checks passed for simulated execution.",
        )

    def approver_roles_for(self, tool_name: str) -> list[str]:
        policy = ACTION_CATALOG.get(tool_name)
        return [r.value for r in policy.approver_roles] if policy else []


ALL_ROLES = [r.value for r in Role]
