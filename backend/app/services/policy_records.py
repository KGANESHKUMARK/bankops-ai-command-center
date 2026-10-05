"""Persist deterministic policy decisions and mirror them into the audit stream."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import PolicyDecisionRecord
from app.policy.engine import Actor, PolicyDecision
from app.services.audit import record_audit


def record_policy_decision(
    db: Session,
    *,
    actor: Actor,
    decision: PolicyDecision,
    action_name: str,
    resource: str | None = None,
    investigation_id: str | None = None,
    action_id: str | None = None,
) -> PolicyDecisionRecord:
    rec = PolicyDecisionRecord(
        tenant_id=actor.tenant_id,
        investigation_id=investigation_id,
        action_id=action_id,
        subject_user_id=actor.user_id,
        subject_role=actor.role,
        action_name=action_name,
        resource=resource,
        risk_level=decision.risk_level.value,
        decision=decision.decision,
        rule_ids=decision.rule_ids,
        explanation=decision.explanation,
        policy_version=decision.policy_version,
    )
    db.add(rec)
    record_audit(
        db,
        tenant_id=actor.tenant_id,
        action="policy.decision",
        resource_type="action" if action_id else "tool",
        resource_id=action_id or action_name,
        outcome="denied" if decision.decision == "deny" else "success",
        actor=actor,
        investigation_id=investigation_id,
        details={
            "tool": action_name,
            "resource": resource,
            "decision": decision.decision,
            "risk_level": decision.risk_level.value,
            "rule_ids": decision.rule_ids,
            "explanation": decision.explanation,
        },
    )
    return rec
