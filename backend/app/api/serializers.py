"""Model -> API dict conversion. Never exposes password hashes, embeddings or raw secrets."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    ActionRecord,
    Approval,
    Incident,
    InvestigationEvent,
    InvestigationRun,
    KnowledgeDocument,
    Service,
    User,
)
from app.policy.engine import Actor, PolicyEngine


class UserCache:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._cache: dict[str, User | None] = {}

    def get(self, user_id: str | None) -> User | None:
        if not user_id:
            return None
        if user_id not in self._cache:
            self._cache[user_id] = self.db.get(User, user_id)
        return self._cache[user_id]

    def name(self, user_id: str | None) -> str | None:
        if user_id == "system":
            return "system"
        user = self.get(user_id)
        return user.username if user else None


def service_keys(db: Session, tenant_id: str) -> dict[str, Service]:
    return {s.id: s for s in db.execute(select(Service).where(Service.tenant_id == tenant_id)).scalars()}


def incident_summary(inc: Incident, services: dict[str, Service]) -> dict[str, Any]:
    primary = services.get(inc.primary_service_id or "")
    return {
        "id": inc.id, "number": inc.number, "title": inc.title, "category": inc.category, "severity": inc.severity,
        "status": inc.status, "classification": inc.classification, "primary_service": primary.key if primary else None,
        "affected_services": inc.affected_services or [], "owner_team": inc.owner_team, "detected_at": inc.detected_at,
        "updated_at": inc.updated_at, "resolved_at": inc.resolved_at, "scenario_key": inc.scenario_key,
        "is_synthetic": inc.is_synthetic,
    }


def event_out(ev: InvestigationEvent) -> dict[str, Any]:
    return {"seq": ev.seq, "created_at": ev.created_at.isoformat(), "event_type": ev.event_type, "agent": ev.agent,
            "tool": ev.tool, "status": ev.status, "message": ev.message, "payload": ev.payload,
            "duration_ms": ev.duration_ms}


def action_out(action: ActionRecord, users: UserCache, approval: Approval | None = None) -> dict[str, Any]:
    return {
        "id": action.id, "investigation_id": action.investigation_id, "incident_id": action.incident_id,
        "step_index": action.step_index, "tool_name": action.tool_name, "target_resource": action.target_resource,
        "parameters": action.parameters, "risk_level": action.risk_level, "status": action.status,
        "requires_approval": action.requires_approval, "policy_decision": action.policy_decision,
        "requested_by": users.name(action.requested_by), "idempotency_key": action.idempotency_key,
        "action_hash": action.action_hash, "preconditions": action.preconditions, "result": action.result,
        "error_code": action.error_code, "verification_status": action.verification_status,
        "verification_detail": action.verification_detail, "rollback_supported": action.rollback_supported,
        "rollback_status": action.rollback_status, "rollback_note": action.rollback_note,
        "rationale": action.rationale, "expected_effect": action.expected_effect,
        "depends_on_step": action.depends_on_step, "attempt_count": action.attempt_count,
        "created_at": action.created_at, "executed_at": action.executed_at, "verified_at": action.verified_at,
        "rolled_back_at": action.rolled_back_at, "simulated": True,
        "approval": approval_brief(approval, users) if approval else None,
    }


def approval_brief(approval: Approval, users: UserCache) -> dict[str, Any]:
    return {"id": approval.id, "status": approval.status, "decided_by": users.name(approval.decided_by),
            "decided_at": approval.decided_at, "reason_code": approval.reason_code, "expires_at": approval.expires_at}


def approval_out(db: Session, approval: Approval, users: UserCache, actor: Actor, policy: PolicyEngine) -> dict[str, Any]:
    action = db.get(ActionRecord, approval.action_id)
    incident = db.get(Incident, approval.incident_id)
    requester = users.get(approval.requested_by)
    check = policy.evaluate_approval(actor, approval=approval, action=action, decision="approve") if action else None
    reject_check = policy.evaluate_approval(actor, approval=approval, action=action, decision="reject") if action else None
    evidence_refs: list[str] = []
    run = db.get(InvestigationRun, approval.investigation_id) if approval.investigation_id else None
    if run and action:
        for planned in ((run.state or {}).get("plan") or {}).get("actions", []):
            if planned.get("step") == action.step_index:
                evidence_refs = planned.get("evidence_refs", [])
    evidence = {e["label"]: e for e in ((run.state or {}).get("evidence") or [])} if run else {}
    return {
        "id": approval.id, "action_id": approval.action_id, "investigation_id": approval.investigation_id,
        "incident_id": approval.incident_id, "incident_number": incident.number if incident else None,
        "incident_title": incident.title if incident else None, "requested_by": requester.username if requester else None,
        "requested_by_role": requester.role if requester else None, "required_roles": approval.required_roles,
        "risk_level": approval.risk_level, "status": approval.status, "expires_at": approval.expires_at,
        "decided_by": users.name(approval.decided_by), "decided_at": approval.decided_at,
        "reason_code": approval.reason_code, "comment": approval.comment, "created_at": approval.created_at,
        "action_hash": approval.action_hash, "target_resource": approval.target_resource,
        "action": action_out(action, users) if action else None,
        "evidence": [{k: evidence[lbl].get(k) for k in ("label", "kind", "title", "citation", "excerpt")}
                     for lbl in evidence_refs if lbl in evidence],
        "can_approve": bool(check and check.decision == "allow"),
        "approve_block_reason": None if check and check.decision == "allow" else (check.explanation if check else "Action missing."),
        "can_reject": bool(reject_check and reject_check.decision == "allow"),
        "reject_block_reason": None if reject_check and reject_check.decision == "allow" else (
            reject_check.explanation if reject_check else "Action missing."),
    }


STATE_KEYS = ("triage", "retrieval", "diagnosis", "plan", "governance", "policy", "execution", "verification",
              "report", "outcome", "degraded_reasons", "sources", "abort_reason", "phase", "notes", "completed")


def run_out(db: Session, run: InvestigationRun, users: UserCache, *, include_state: bool = True,
            settings: Settings | None = None) -> dict[str, Any]:
    incident = db.get(Incident, run.incident_id)
    data: dict[str, Any] = {
        "id": run.id, "incident_id": run.incident_id, "incident_number": incident.number if incident else None,
        "incident_title": incident.title if incident else None, "status": run.status, "outcome": run.outcome,
        "phase": run.phase, "current_node": run.current_node, "requested_by": users.name(run.requested_by),
        "created_at": run.created_at, "started_at": run.started_at, "completed_at": run.completed_at,
        "updated_at": run.updated_at, "step_count": run.step_count, "tool_call_count": run.tool_call_count,
        "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
        "estimated_cost_usd": run.estimated_cost_usd, "provider": run.provider, "model": run.model,
        "model_mode": run.model_mode, "prompt_versions": run.prompt_versions, "workflow_version": run.workflow_version,
        "index_version": run.index_version, "policy_version": run.policy_version, "degraded": run.degraded,
        "confidence": run.confidence, "risk_level": run.risk_level, "error_code": run.error_code,
        "execution_mode": run.execution_mode, "is_evaluation": run.is_evaluation, "event_seq": run.event_seq,
    }
    if settings is not None:
        data["limits"] = {"max_steps": settings.workflow_max_steps, "max_tool_calls": settings.workflow_max_tool_calls,
                          "token_budget": settings.workflow_token_budget,
                          "step_timeout_seconds": settings.workflow_step_timeout_seconds,
                          "total_timeout_seconds": settings.workflow_total_timeout_seconds}
    if include_state:
        state = run.state or {}
        data["state"] = {k: state.get(k) for k in STATE_KEYS}
        data["state"]["evidence"] = [
            {k: v for k, v in e.items() if k != "text"} for e in (state.get("evidence") or [])
        ]
        actions = db.execute(select(ActionRecord).where(ActionRecord.investigation_id == run.id)
                             .order_by(ActionRecord.step_index)).scalars().all()
        approvals = {a.action_id: a for a in db.execute(select(Approval).where(Approval.investigation_id == run.id)).scalars()}
        data["actions"] = [action_out(a, users, approvals.get(a.id)) for a in actions]
    return data


def document_out(doc: KnowledgeDocument, settings: Settings) -> dict[str, Any]:
    return {
        "id": doc.id, "doc_key": doc.doc_key, "title": doc.title, "version": doc.version, "source": doc.source,
        "source_type": doc.source_type, "classification": doc.classification, "allowed_roles": doc.allowed_roles,
        "tags": doc.tags, "status": doc.status, "status_detail": doc.status_detail, "chunk_count": doc.chunk_count,
        "injection_flag_count": doc.injection_flag_count, "index_version": doc.index_version,
        "index_current": doc.index_version == settings.index_version, "content_hash": doc.content_hash,
        "byte_size": doc.byte_size, "is_synthetic": doc.is_synthetic, "created_at": doc.created_at,
        "updated_at": doc.updated_at, "deleted_at": doc.deleted_at, "retention_until": doc.retention_until,
    }
