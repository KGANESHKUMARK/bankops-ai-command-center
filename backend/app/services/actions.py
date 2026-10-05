"""Simulated remediation: plan -> policy-gated action records -> idempotent execution -> verification.

Execution uses explicit transaction boundaries:
  T1: compare-and-set status approved -> executing (commit)
  T2: preconditions + simulated mutation + succeeded (commit), or rollback and T3: failed
A crash between T1 and T2 leaves the action in `executing`; it is never re-run
automatically (non-idempotent actions are not blindly retried) and must be verified.
"""

from __future__ import annotations

import hashlib
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agents.simulation import (
    MUTATIONS,
    TARGET_OF,
    SimulationError,
    get_service,
    mark_incident,
    restore_snapshot,
    snapshot,
)
from app.agents.tools import REGISTRY, ToolContext, ToolError, ToolExecutor
from app.core.config import Settings
from app.core.logging import get_logger, redact
from app.db.base import utcnow
from app.domain import ActionStatus, ApprovalStatus, IncidentStatus, RiskLevel, VerificationStatus
from app.models import ActionRecord, Approval, Incident, IncidentEvent, InvestigationRun
from app.policy.catalog import ACTION_CATALOG
from app.policy.engine import Actor, PolicyDecision, PolicyEngine, canonical_json, compute_action_hash
from app.services.audit import record_audit
from app.services.flags import fault_enabled
from app.services.policy_records import record_policy_decision

log = get_logger("services.actions")


class ActionError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def idempotency_key(investigation_id: str | None, step: int, tool: str, params: dict[str, Any], plan_version: int) -> str:
    raw = f"{investigation_id}:{step}:{tool}:{canonical_json(params)}:{plan_version}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _timeline(db: Session, incident: Incident, event_type: str, summary: str, details: dict[str, Any]) -> None:
    db.add(IncidentEvent(incident_id=incident.id, tenant_id=incident.tenant_id, occurred_at=utcnow(),
                         event_type=event_type, source="bankops-ai", summary=summary, details=details))


class ActionService:
    def __init__(self, settings: Settings, policy: PolicyEngine, tools: ToolExecutor) -> None:
        self.settings = settings
        self.policy = policy
        self.tools = tools

    # ---------------------------------------------------------------- policy gate
    def gate_plan(
        self,
        db: Session,
        *,
        run: InvestigationRun,
        incident: Incident,
        requester: Actor,
        planned: list[dict[str, Any]],
        dry_run: bool,
    ) -> list[dict[str, Any]]:
        """Evaluate every proposed action deterministically and persist action/approval records."""
        outcomes: list[dict[str, Any]] = []
        for pa in sorted(planned, key=lambda p: p.get("step", 0)):
            tool = str(pa.get("tool_name", ""))[:80]
            target = str(pa.get("target_resource", ""))[:100]
            raw_params = pa.get("parameters")
            params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
            step = int(pa.get("step", 0))
            decision = self.policy.evaluate_action(
                requester,
                tool_name=tool,
                target_resource=target,
                incident_tenant_id=incident.tenant_id,
                incident_status=incident.status,
                incident_classification=incident.classification,
            )
            clean_params: dict[str, Any] = redact(params)
            if decision.decision != "deny" and tool in REGISTRY:
                try:
                    model = self.tools.validate_args(tool, params)
                    clean_params = model.model_dump(mode="json")
                    if REGISTRY[tool].mutating and TARGET_OF[tool](model) != target:
                        decision = PolicyDecision(
                            decision="deny", risk_level=decision.risk_level, rule_ids=["P-005"],
                            reasons=["Target mismatch"],
                            explanation=f"DENIED (P-005): parameters target '{TARGET_OF[tool](model)}' but the plan "
                            f"declared '{target}'.",
                        )
                except ToolError as exc:
                    decision = PolicyDecision(
                        decision="deny", risk_level=decision.risk_level, rule_ids=["P-012"],
                        reasons=["Argument validation failed"],
                        explanation=f"DENIED (P-012): {exc.message}",
                    )
            action_id: str | None = None
            approval_id: str | None = None
            if not dry_run:
                action, approval = self._persist(db, run, incident, requester, pa, tool, target, clean_params, step, decision)
                action_id, approval_id = action.id, approval.id if approval else None
            record_policy_decision(db, actor=requester, decision=decision, action_name=tool, resource=target,
                                   investigation_id=run.id, action_id=action_id)
            outcomes.append({
                "step": step, "tool_name": tool, "target_resource": target, "parameters": clean_params,
                "decision": decision.model_dump(mode="json"), "action_id": action_id, "approval_id": approval_id,
                "depends_on_step": pa.get("depends_on_step"),
            })
        return outcomes

    def _persist(
        self, db: Session, run: InvestigationRun, incident: Incident, requester: Actor, pa: dict[str, Any],
        tool: str, target: str, params: dict[str, Any], step: int, decision: PolicyDecision,
    ) -> tuple[ActionRecord, Approval | None]:
        plan_version = int(run.state.get("plan_version", 1)) if run.state else 1
        key = idempotency_key(run.id, step, tool, params, plan_version)
        existing = db.execute(select(ActionRecord).where(ActionRecord.idempotency_key == key)).scalar_one_or_none()
        if existing is not None:
            approval = db.execute(select(Approval).where(Approval.action_id == existing.id)).scalar_one_or_none()
            return existing, approval
        risk = decision.risk_level if tool in ACTION_CATALOG else RiskLevel.PROHIBITED
        status = {"deny": ActionStatus.DENIED, "allow": ActionStatus.APPROVED_BY_POLICY,
                  "require_approval": ActionStatus.PENDING_APPROVAL}[decision.decision]
        catalog = ACTION_CATALOG.get(tool)
        action_hash = compute_action_hash(tool_name=tool, target_resource=target, parameters=params,
                                          incident_id=incident.id, investigation_id=run.id,
                                          plan_version=plan_version, step_index=step)
        action = ActionRecord(
            tenant_id=incident.tenant_id, investigation_id=run.id, incident_id=incident.id, step_index=step,
            tool_name=tool, target_resource=target, parameters=params, action_hash=action_hash,
            risk_level=risk.value, status=status.value, requires_approval=decision.decision == "require_approval",
            policy_decision=decision.model_dump(mode="json"), requested_by=requester.user_id, idempotency_key=key,
            rollback_supported=bool(catalog and catalog.rollback_supported),
            rollback_status="available_after_execution" if catalog and catalog.rollback_supported else "not_supported",
            rollback_note=catalog.rollback_note if catalog else "Not applicable.",
            plan_version=plan_version, rationale=str(pa.get("rationale", ""))[:800],
            expected_effect=str(pa.get("expected_effect", ""))[:500], depends_on_step=pa.get("depends_on_step"),
        )
        db.add(action)
        db.flush()
        approval = None
        if decision.decision == "require_approval":
            approval = Approval(
                tenant_id=incident.tenant_id, action_id=action.id, investigation_id=run.id, incident_id=incident.id,
                requested_by=requester.user_id, required_roles=decision.required_approver_roles,
                risk_level=risk.value, action_hash=action_hash, target_resource=target,
                expires_at=utcnow() + timedelta(minutes=self.settings.approval_ttl_minutes),
            )
            db.add(approval)
            db.flush()
            record_audit(db, tenant_id=incident.tenant_id, action="approval.requested", resource_type="approval",
                         resource_id=approval.id, actor=requester, investigation_id=run.id,
                         details={"tool": tool, "risk": risk.value, "required_roles": approval.required_roles,
                                  "expires_at": approval.expires_at.isoformat()})
        record_audit(db, tenant_id=incident.tenant_id, action="action.proposed", resource_type="action",
                     resource_id=action.id, actor=requester, investigation_id=run.id,
                     outcome="denied" if status == ActionStatus.DENIED else "success",
                     details={"tool": tool, "target": target, "status": status.value, "risk": risk.value})
        return action, approval

    # ------------------------------------------------------------------ execution
    def execute(self, db: Session, action_id: str, *, actor: Actor) -> ActionRecord:
        res = db.execute(
            update(ActionRecord)
            .where(ActionRecord.id == action_id,
                   ActionRecord.status.in_([ActionStatus.APPROVED.value, ActionStatus.APPROVED_BY_POLICY.value]))
            .values(status=ActionStatus.EXECUTING.value, attempt_count=ActionRecord.attempt_count + 1, updated_at=utcnow())
        )
        db.commit()
        action = db.get(ActionRecord, action_id)
        assert action is not None
        db.refresh(action)
        if res.rowcount != 1:  # type: ignore[attr-defined]
            return action  # idempotent: already executed, executing, or not executable
        approval = db.execute(select(Approval).where(Approval.action_id == action.id)).scalar_one_or_none()
        incident = db.get(Incident, action.incident_id)
        assert incident is not None
        decision = self.policy.evaluate_execution(action=action, approval=approval)
        record_policy_decision(db, actor=actor, decision=decision, action_name=action.tool_name,
                               resource=action.target_resource, investigation_id=action.investigation_id,
                               action_id=action.id)
        if decision.decision != "allow":
            return self._finish(db, action, incident, actor, ActionStatus.FAILED, error_code="policy_recheck_failed",
                                result={"explanation": decision.explanation})
        started = time.perf_counter()
        try:
            args = self.tools.validate_args(action.tool_name, action.parameters)
            mutation = MUTATIONS[action.tool_name]
            if fault_enabled(db, "downstream_outage"):
                checks = [{"check": "orchestration_api_reachable", "passed": False,
                           "detail": "Synthetic orchestration API unavailable (injected fault)."}]
            else:
                checks = mutation.preconditions(db, action.tenant_id, args)
            action.preconditions = checks
            if not all(c["passed"] for c in checks):
                return self._finish(db, action, incident, actor, ActionStatus.SKIPPED, error_code="preconditions_not_met",
                                    result={"failed_checks": [c for c in checks if not c["passed"]]})
            affected = [get_service(db, action.tenant_id, key) for key in mutation.affected(args)]
            state_before = snapshot(affected)
            result = mutation.apply(db, action.tenant_id, args, action.id)
            if time.perf_counter() - started > self.settings.tool_timeout_seconds:
                raise ActionError("action_timeout", "Simulated action exceeded its deadline.")
            action.state_before = state_before
            return self._finish(db, action, incident, actor, ActionStatus.SUCCEEDED, result=result)
        except (SimulationError, ToolError, ActionError, KeyError, ValueError) as exc:
            db.rollback()
            action = db.get(ActionRecord, action_id)
            assert action is not None
            incident = db.get(Incident, action.incident_id)
            assert incident is not None
            code = getattr(exc, "code", type(exc).__name__)
            return self._finish(db, action, incident, actor, ActionStatus.FAILED, error_code=str(code)[:64],
                                result={"message": "Simulated execution failed; no partial state was committed."})

    def _finish(self, db: Session, action: ActionRecord, incident: Incident, actor: Actor, status: ActionStatus, *,
                error_code: str | None = None, result: dict[str, Any] | None = None) -> ActionRecord:
        action.status = status.value
        action.error_code = error_code
        action.result = result
        action.executed_at = utcnow()
        if status == ActionStatus.SUCCEEDED and action.rollback_supported:
            action.rollback_status = "available"
        _timeline(db, incident, "action", f"[SIMULATED] {action.tool_name} on {action.target_resource}: {status.value}",
                  {"action_id": action.id, "status": status.value, "error_code": error_code})
        record_audit(db, tenant_id=action.tenant_id, action=f"action.{status.value}", resource_type="action",
                     resource_id=action.id, actor=actor, investigation_id=action.investigation_id,
                     outcome="success" if status == ActionStatus.SUCCEEDED else "failure",
                     details={"tool": action.tool_name, "target": action.target_resource, "error_code": error_code,
                              "idempotency_key": action.idempotency_key[:16]})
        db.commit()
        log.info("action finished", extra={"action_id": action.id, "status": status.value, "error_code": error_code})
        return action

    def mark_skipped(self, db: Session, action: ActionRecord, actor: Actor, reason: str) -> None:
        if action.status in (ActionStatus.APPROVED.value, ActionStatus.APPROVED_BY_POLICY.value):
            incident = db.get(Incident, action.incident_id)
            assert incident is not None
            self._finish(db, action, incident, actor, ActionStatus.SKIPPED, error_code=reason[:64],
                         result={"reason": reason})

    # --------------------------------------------------------------- verification
    def verify(self, db: Session, action: ActionRecord, *, actor: Actor, ctx: ToolContext) -> dict[str, Any]:
        incident = db.get(Incident, action.incident_id)
        assert incident is not None
        health = self.tools.invoke(ctx, "verify_service_health", {"service_key": action.target_resource}, incident=incident)
        resolution = self.tools.invoke(ctx, "verify_incident_resolution", {"incident_id": incident.id}, incident=incident)
        if not resolution.ok or resolution.data is None:
            status = VerificationStatus.ERROR
            detail: dict[str, Any] = {"error_code": resolution.error_code, "message": resolution.message}
        else:
            status = VerificationStatus(resolution.data["status"])
            detail = {"resolution": resolution.data, "target_health": health.data if health.ok else {"error_code": health.error_code}}
        action.verification_status = status.value
        action.verification_detail = detail
        action.verified_at = utcnow()
        if status == VerificationStatus.RESOLVED:
            mark_incident(db, incident, IncidentStatus.RESOLVED, "Resolution criteria verified after simulated remediation.")
        record_audit(db, tenant_id=action.tenant_id, action="action.verified", resource_type="action",
                     resource_id=action.id, actor=actor, investigation_id=action.investigation_id,
                     details={"verification_status": status.value})
        db.commit()
        return {"status": status.value, **detail}

    # ------------------------------------------------------------------- rollback
    def rollback(self, db: Session, action: ActionRecord, *, actor: Actor, reason: str) -> ActionRecord:
        if not action.rollback_supported:
            raise ActionError("rollback_not_supported", action.rollback_note or "Rollback is not supported for this action.")
        if action.status != ActionStatus.SUCCEEDED.value or not action.state_before:
            raise ActionError("invalid_state", f"Only succeeded actions with a state snapshot can be rolled back (status: {action.status}).")
        res = db.execute(
            update(ActionRecord)
            .where(ActionRecord.id == action.id, ActionRecord.status == ActionStatus.SUCCEEDED.value)
            .values(status=ActionStatus.ROLLED_BACK.value, rollback_status="rolled_back", rolled_back_at=utcnow())
        )
        if res.rowcount != 1:  # type: ignore[attr-defined]
            db.rollback()
            raise ActionError("concurrent_modification", "Action state changed concurrently.")
        restored = restore_snapshot(db, action.tenant_id, action.state_before)
        incident = db.get(Incident, action.incident_id)
        assert incident is not None
        if incident.status == IncidentStatus.RESOLVED.value:
            mark_incident(db, incident, IncidentStatus.INVESTIGATING, f"Incident reopened after simulated rollback of {action.tool_name}.")
        _timeline(db, incident, "action", f"[SIMULATED] Rollback of {action.tool_name}: restored {', '.join(restored)}",
                  {"action_id": action.id, "reason": reason[:300]})
        record_audit(db, tenant_id=action.tenant_id, action="action.rolled_back", resource_type="action",
                     resource_id=action.id, actor=actor, investigation_id=action.investigation_id,
                     details={"restored": restored, "reason": reason[:300]})
        db.commit()
        db.refresh(action)
        return action

    @staticmethod
    def approval_for(db: Session, action_id: str) -> Approval | None:
        return db.execute(select(Approval).where(Approval.action_id == action_id)).scalar_one_or_none()


def pending_approval_count(db: Session, investigation_id: str) -> int:
    return len(db.execute(select(Approval.id).where(
        Approval.investigation_id == investigation_id, Approval.status == ApprovalStatus.PENDING.value)).all())
