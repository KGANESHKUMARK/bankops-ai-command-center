"""Investigation lifecycle: start, resume after approval, cancel, and crash recovery."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agents.runner import WorkflowRunner
from app.agents.workflow import WORKFLOW_VERSION
from app.ai.gateway import ModelGateway
from app.ai.prompts import prompt_versions
from app.core.config import Settings
from app.core.context import correlation_id_var, request_id_var
from app.db.base import utcnow
from app.domain import ActionStatus, ApprovalStatus, InvestigationStatus
from app.models import ActionRecord, Approval, Incident, InvestigationEvent, InvestigationRun
from app.policy.engine import POLICY_VERSION, Actor
from app.rag.injection import neutralize
from app.services.actions import pending_approval_count
from app.services.audit import record_audit


class InvestigationError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


ACTIVE = (InvestigationStatus.QUEUED.value, InvestigationStatus.RUNNING.value)


class InvestigationService:
    def __init__(self, settings: Settings, runner: WorkflowRunner, gateway: ModelGateway) -> None:
        self.settings = settings
        self.runner = runner
        self.gateway = gateway

    def start(
        self,
        db: Session,
        *,
        incident: Incident,
        actor: Actor,
        notes: str | None,
        execution_mode: str = "live",
        is_evaluation: bool = False,
        sync: bool = False,
    ) -> InvestigationRun:
        if not is_evaluation:
            active = db.execute(select(InvestigationRun.id).where(
                InvestigationRun.incident_id == incident.id, InvestigationRun.status.in_(ACTIVE),
                InvestigationRun.is_evaluation.is_(False))).first()
            if active:
                raise InvestigationError("investigation_in_progress",
                                         "An investigation for this incident is already running.")
            self._supersede_awaiting(db, incident, actor)
        clean_notes = neutralize(notes.strip()).text[:1000] if notes and notes.strip() else None
        run = InvestigationRun(
            tenant_id=incident.tenant_id, incident_id=incident.id, requested_by=actor.user_id,
            status=InvestigationStatus.QUEUED.value, phase="analysis", notes=clean_notes,
            provider=self.gateway.provider.name, model=self.gateway.provider.model, model_mode=self.gateway.mode,
            prompt_versions=prompt_versions(), workflow_version=WORKFLOW_VERSION,
            index_version=self.settings.index_version, policy_version=POLICY_VERSION,
            state={"phase": "analysis", "completed": [], "step_count": 0, "plan_version": 1},
            is_evaluation=is_evaluation, execution_mode=execution_mode,
            correlation_id=correlation_id_var.get() or request_id_var.get(),
        )
        db.add(run)
        db.flush()
        notes_neutralized = bool(notes) and clean_notes != (notes or "").strip()[:1000]
        db.add(InvestigationEvent(investigation_id=run.id, seq=1, event_type="status_change", status="queued",
                                  message=f"Investigation queued by {actor.username} ({execution_mode}).",
                                  agent="Orchestrator",
                                  payload={"notes_provided": bool(clean_notes), "notes_neutralized": notes_neutralized}))
        run.event_seq = 1
        record_audit(db, tenant_id=incident.tenant_id, action="investigation.started", resource_type="investigation",
                     resource_id=run.id, actor=actor, investigation_id=run.id,
                     details={"incident": incident.number, "execution_mode": execution_mode,
                              "model_mode": self.gateway.mode, "evaluation": is_evaluation})
        db.commit()
        self.runner.submit(run.id, sync=sync)
        db.refresh(run)
        return run

    def _supersede_awaiting(self, db: Session, incident: Incident, actor: Actor) -> None:
        older = db.execute(select(InvestigationRun).where(
            InvestigationRun.incident_id == incident.id,
            InvestigationRun.status.in_([InvestigationStatus.AWAITING_APPROVAL.value, InvestigationStatus.INTERRUPTED.value]),
        )).scalars().all()
        for run in older:
            run.status = InvestigationStatus.CANCELLED.value
            run.error_code = "superseded_by_new_investigation"
            run.completed_at = utcnow()
            for approval in db.execute(select(Approval).where(Approval.investigation_id == run.id,
                                                              Approval.status == ApprovalStatus.PENDING.value)).scalars():
                approval.status = ApprovalStatus.INVALIDATED.value
                approval.reason_code = "PLAN_SUPERSEDED"
                action = db.get(ActionRecord, approval.action_id)
                if action and action.status == ActionStatus.PENDING_APPROVAL.value:
                    action.status = ActionStatus.INVALIDATED.value
            record_audit(db, tenant_id=run.tenant_id, action="investigation.superseded", resource_type="investigation",
                         resource_id=run.id, actor=actor, investigation_id=run.id,
                         details={"reason": "new investigation started; pending approvals invalidated"})

    def resume(self, db: Session, run: InvestigationRun, actor: Actor, *, sync: bool = False) -> InvestigationRun:
        if run.status not in (InvestigationStatus.AWAITING_APPROVAL.value, InvestigationStatus.INTERRUPTED.value):
            raise InvestigationError("not_resumable", f"Investigation is {run.status}; only awaiting_approval or "
                                     "interrupted runs can be resumed.")
        pending = pending_approval_count(db, run.id)
        if pending:
            raise InvestigationError("approvals_pending", f"{pending} approval(s) are still pending.")
        state = dict(run.state or {})
        if run.status == InvestigationStatus.AWAITING_APPROVAL.value or state.get("phase") == "awaiting_approval":
            state["phase"] = "execution"
        res = db.execute(
            update(InvestigationRun)
            .where(InvestigationRun.id == run.id, InvestigationRun.status == run.status)
            .values(status=InvestigationStatus.QUEUED.value, state=state, updated_at=utcnow())
        )
        if res.rowcount != 1:  # type: ignore[attr-defined]
            db.rollback()
            raise InvestigationError("concurrent_modification", "Investigation state changed concurrently.")
        record_audit(db, tenant_id=run.tenant_id, action="investigation.resumed", resource_type="investigation",
                     resource_id=run.id, actor=actor, investigation_id=run.id, details={"phase": state.get("phase")})
        db.commit()
        self.runner.submit(run.id, sync=sync)
        db.refresh(run)
        return run

    def cancel(self, db: Session, run: InvestigationRun, actor: Actor, reason: str) -> InvestigationRun:
        if run.status in (InvestigationStatus.COMPLETED.value, InvestigationStatus.FAILED.value,
                          InvestigationStatus.CANCELLED.value):
            raise InvestigationError("not_cancellable", f"Investigation is already {run.status}.")
        run.status = InvestigationStatus.CANCELLED.value
        run.error_code = "cancelled_by_user"
        run.completed_at = utcnow()
        for approval in db.execute(select(Approval).where(Approval.investigation_id == run.id,
                                                          Approval.status == ApprovalStatus.PENDING.value)).scalars():
            approval.status = ApprovalStatus.CANCELLED.value
            approval.reason_code = "INVESTIGATION_CANCELLED"
            action = db.get(ActionRecord, approval.action_id)
            if action and action.status == ActionStatus.PENDING_APPROVAL.value:
                action.status = ActionStatus.CANCELLED.value
        record_audit(db, tenant_id=run.tenant_id, action="investigation.cancelled", resource_type="investigation",
                     resource_id=run.id, actor=actor, investigation_id=run.id, details={"reason": reason[:300]})
        db.commit()
        return run

    def recover_stale(self, db: Session) -> int:
        """Mark runs orphaned by a crash/restart as interrupted (resumable, never auto-re-executed)."""
        cutoff = utcnow() - timedelta(seconds=self.settings.workflow_total_timeout_seconds)
        res = db.execute(
            update(InvestigationRun)
            .where(InvestigationRun.status.in_(ACTIVE), InvestigationRun.updated_at < cutoff)
            .values(status=InvestigationStatus.INTERRUPTED.value, error_code="interrupted_by_restart")
        )
        db.commit()
        return int(res.rowcount or 0)  # type: ignore[attr-defined]
