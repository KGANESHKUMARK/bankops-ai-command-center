"""Human approval workflow: approve / reject / cancel / expire / invalidate, all policy-checked and audited."""

from __future__ import annotations

import re
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import utcnow
from app.domain import ActionStatus, ApprovalStatus
from app.models import ActionRecord, Approval, IncidentEvent
from app.policy.engine import Actor, PolicyEngine
from app.policy.permissions import Permission, has_permission
from app.rag.injection import neutralize
from app.services.audit import record_audit
from app.services.policy_records import record_policy_decision

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class ApprovalError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def clean_comment(text: str | None) -> str | None:
    if not text or not text.strip():
        return None
    return neutralize(_CTRL.sub("", text.strip())).text[:1000]


def _as_utc_expired(approval: Approval) -> bool:
    return approval.expires_at <= utcnow()


class ApprovalService:
    def __init__(self, settings: Settings, policy: PolicyEngine) -> None:
        self.settings = settings
        self.policy = policy

    def _load(self, db: Session, approval_id: str, actor: Actor) -> tuple[Approval, ActionRecord]:
        approval = db.get(Approval, approval_id)
        if approval is None or approval.tenant_id != actor.tenant_id:
            raise ApprovalError("not_found", "Approval not found.", 404)
        action = db.get(ActionRecord, approval.action_id)
        assert action is not None
        return approval, action

    def _timeline(self, db: Session, approval: Approval, summary: str) -> None:
        db.add(IncidentEvent(incident_id=approval.incident_id, tenant_id=approval.tenant_id, occurred_at=utcnow(),
                             event_type="approval", source="approval-center", summary=summary,
                             details={"approval_id": approval.id, "status": approval.status}))

    def expire_stale(self, db: Session, tenant_id: str) -> int:
        stale = db.execute(select(Approval).where(Approval.tenant_id == tenant_id,
                                                  Approval.status == ApprovalStatus.PENDING.value,
                                                  Approval.expires_at <= utcnow())).scalars().all()
        for approval in stale:
            approval.status = ApprovalStatus.EXPIRED.value
            action = db.get(ActionRecord, approval.action_id)
            if action and action.status == ActionStatus.PENDING_APPROVAL.value:
                action.status = ActionStatus.EXPIRED.value
            self._timeline(db, approval, "Approval request expired without a decision.")
            record_audit(db, tenant_id=tenant_id, action="approval.expired", resource_type="approval",
                         resource_id=approval.id, outcome="info", investigation_id=approval.investigation_id,
                         details={"action_id": approval.action_id})
        if stale:
            db.commit()
        return len(stale)

    def decide(
        self,
        db: Session,
        approval_id: str,
        actor: Actor,
        decision: Literal["approve", "reject"],
        *,
        reason_code: str,
        comment: str | None,
    ) -> Approval:
        approval, action = self._load(db, approval_id, actor)
        if approval.status == ApprovalStatus.PENDING.value and _as_utc_expired(approval):
            self.expire_stale(db, actor.tenant_id)
            db.refresh(approval)
            db.refresh(action)
        pd = self.policy.evaluate_approval(actor, approval=approval, action=action, decision=decision)
        record_policy_decision(db, actor=actor, decision=pd, action_name=f"approval.{decision}",
                               resource=approval.target_resource, investigation_id=approval.investigation_id,
                               action_id=action.id)
        if pd.decision != "allow":
            record_audit(db, tenant_id=actor.tenant_id, action=f"approval.{decision}_denied", resource_type="approval",
                         resource_id=approval.id, outcome="denied", actor=actor,
                         investigation_id=approval.investigation_id,
                         details={"rule_ids": pd.rule_ids, "explanation": pd.explanation})
            db.commit()
            status = 403 if any(r in pd.rule_ids for r in ("A-001", "A-002", "A-005", "A-007")) else 409
            raise ApprovalError(pd.rule_ids[0], pd.explanation, status)

        new_status = ApprovalStatus.APPROVED if decision == "approve" else ApprovalStatus.REJECTED
        res = db.execute(
            update(Approval)
            .where(Approval.id == approval.id, Approval.status == ApprovalStatus.PENDING.value)
            .values(status=new_status.value, decided_by=actor.user_id, decided_at=utcnow(),
                    reason_code=reason_code, comment=clean_comment(comment))
        )
        if res.rowcount != 1:  # type: ignore[attr-defined]
            db.rollback()
            raise ApprovalError("A-003", "Approval was decided concurrently; decisions are final.", 409)
        action.status = (ActionStatus.APPROVED if decision == "approve" else ActionStatus.REJECTED).value
        db.flush()
        db.refresh(approval)
        self._timeline(db, approval, f"{action.tool_name} {new_status.value} by {actor.username} ({reason_code}).")
        record_audit(db, tenant_id=actor.tenant_id, action=f"approval.{new_status.value}", resource_type="approval",
                     resource_id=approval.id, actor=actor, investigation_id=approval.investigation_id,
                     details={"action_id": action.id, "tool": action.tool_name, "risk": approval.risk_level,
                              "reason_code": reason_code, "action_hash": approval.action_hash[:16]})
        db.commit()
        return approval

    def cancel(self, db: Session, approval_id: str, actor: Actor, *, reason_code: str, comment: str | None) -> Approval:
        approval, action = self._load(db, approval_id, actor)
        is_requester = approval.requested_by == actor.user_id
        if not (is_requester and has_permission(actor.role, Permission.APPROVALS_CANCEL)) and not has_permission(
            actor.role, Permission.APPROVALS_DECIDE
        ):
            raise ApprovalError("forbidden", "Only the requester or an approver may cancel this request.", 403)
        res = db.execute(
            update(Approval)
            .where(Approval.id == approval.id, Approval.status == ApprovalStatus.PENDING.value)
            .values(status=ApprovalStatus.CANCELLED.value, decided_by=actor.user_id, decided_at=utcnow(),
                    reason_code=reason_code, comment=clean_comment(comment))
        )
        if res.rowcount != 1:  # type: ignore[attr-defined]
            db.rollback()
            raise ApprovalError("A-003", f"Approval is already {approval.status}.", 409)
        if action.status == ActionStatus.PENDING_APPROVAL.value:
            action.status = ActionStatus.CANCELLED.value
        db.flush()
        db.refresh(approval)
        self._timeline(db, approval, f"Approval request for {action.tool_name} cancelled ({reason_code}).")
        record_audit(db, tenant_id=actor.tenant_id, action="approval.cancelled", resource_type="approval",
                     resource_id=approval.id, actor=actor, investigation_id=approval.investigation_id,
                     details={"reason_code": reason_code, "action_id": action.id})
        db.commit()
        return approval

    def invalidate_for_incident(self, db: Session, incident_id: str, *, exclude_investigation_id: str, actor: Actor | None) -> int:
        """A new plan for the incident supersedes older pending approvals (plan change => approval invalid)."""
        pending = db.execute(select(Approval).where(Approval.incident_id == incident_id,
                                                    Approval.status == ApprovalStatus.PENDING.value,
                                                    Approval.investigation_id != exclude_investigation_id)).scalars().all()
        for approval in pending:
            approval.status = ApprovalStatus.INVALIDATED.value
            approval.reason_code = "PLAN_SUPERSEDED"
            action = db.get(ActionRecord, approval.action_id)
            if action and action.status == ActionStatus.PENDING_APPROVAL.value:
                action.status = ActionStatus.INVALIDATED.value
            self._timeline(db, approval, "Pending approval invalidated: superseded by a newer investigation plan.")
            record_audit(db, tenant_id=approval.tenant_id, action="approval.invalidated", resource_type="approval",
                         resource_id=approval.id, actor=actor, investigation_id=approval.investigation_id,
                         details={"reason": "plan_superseded", "superseded_by": exclude_investigation_id})
        return len(pending)
