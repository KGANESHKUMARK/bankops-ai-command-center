from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import CurrentUser, DbDep, require
from app.api.serializers import incident_summary, service_keys
from app.domain import CLASSIFICATION_RANK, ApprovalStatus, Classification, InvestigationStatus, clearance_rank
from app.models import Approval, EvaluationRun, Incident, InvestigationEvent, InvestigationRun
from app.policy.permissions import Permission

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
OPEN = ("open", "investigating", "awaiting_approval", "mitigated")
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@router.get("/summary", summary="Overview KPIs, trends, high-risk incidents, AI quality and recent activity")
def summary(db: DbDep, current: CurrentUser = Depends(require(Permission.DASHBOARD_READ))) -> dict[str, Any]:
    actor = current.actor
    allowed = [c.value for c, r in CLASSIFICATION_RANK.items() if r <= clearance_rank(actor.role)]
    incidents = db.execute(select(Incident).where(Incident.tenant_id == actor.tenant_id,
                                                  Incident.classification.in_(allowed))).scalars().all()
    services = service_keys(db, actor.tenant_id)
    open_inc = [i for i in incidents if i.status in OPEN]
    resolved = [i for i in incidents if i.resolved_at is not None]
    resolution_minutes = [(i.resolved_at - i.detected_at).total_seconds() / 60 for i in resolved if i.resolved_at is not None]
    mttr = (sum(resolution_minutes) / len(resolution_minutes)) if resolution_minutes else None
    latest = max((i.detected_at for i in incidents), default=None)
    trend: list[dict[str, Any]] = []
    if latest:
        start = (latest - timedelta(days=29)).date()
        per_day: dict[str, Counter[str]] = {}
        for i in incidents:
            if i.detected_at.date() >= start:
                per_day.setdefault(i.detected_at.date().isoformat(), Counter())[i.severity] += 1
        for d in range(30):
            day = (start + timedelta(days=d)).isoformat()
            c = per_day.get(day, Counter())
            trend.append({"date": day, **{s: c.get(s, 0) for s in SEV_ORDER}, "total": sum(c.values())})
    high_risk = sorted([i for i in open_inc if i.severity in ("critical", "high")],
                       key=lambda i: (SEV_ORDER[i.severity], i.detected_at))[:6]
    runs = db.execute(select(InvestigationRun).where(InvestigationRun.tenant_id == actor.tenant_id,
                                                     InvestigationRun.is_evaluation.is_(False))).scalars().all()
    finished = [r for r in runs if r.completed_at and r.started_at]
    durations = sorted((r.completed_at - r.started_at).total_seconds() for r in finished)  # type: ignore[operator]
    pending = db.execute(select(Approval).where(Approval.tenant_id == actor.tenant_id,
                                                Approval.status == ApprovalStatus.PENDING.value)).scalars().all()
    latest_eval = db.execute(select(EvaluationRun).where(EvaluationRun.tenant_id == actor.tenant_id,
                                                         EvaluationRun.status == "completed")
                             .order_by(EvaluationRun.created_at.desc()).limit(1)).scalar_one_or_none()
    visible_ids = {i.id for i in incidents}
    recent = db.execute(
        select(InvestigationEvent, InvestigationRun)
        .join(InvestigationRun, InvestigationRun.id == InvestigationEvent.investigation_id)
        .where(InvestigationRun.tenant_id == actor.tenant_id, InvestigationRun.is_evaluation.is_(False),
               InvestigationEvent.event_type.in_(["status_change", "action_executed", "policy_decision"]))
        .order_by(InvestigationEvent.id.desc()).limit(40)
    ).all()
    numbers = {i.id: i.number for i in incidents}
    activity = [
        {"at": ev.created_at, "investigation_id": run.id, "incident_number": numbers.get(run.incident_id),
         "event_type": ev.event_type, "status": ev.status, "message": ev.message}
        for ev, run in recent if run.incident_id in visible_ids
    ][:12]
    return {
        "synthetic": True,
        "kpis": {
            "open_incidents": len(open_inc),
            "critical_high_open": sum(1 for i in open_inc if i.severity in ("critical", "high")),
            "awaiting_approval": sum(1 for i in open_inc if i.status == "awaiting_approval"),
            "pending_approvals": len(pending),
            "resolved_incidents": len(resolved),
            "mttr_minutes_synthetic": round(mttr, 1) if mttr is not None else None,
            "investigations_total": len(runs),
            "investigations_running": sum(1 for r in runs if r.status in (InvestigationStatus.RUNNING, InvestigationStatus.QUEUED)),
        },
        "by_severity": dict(Counter(i.severity for i in open_inc)),
        "by_status": dict(Counter(i.status for i in incidents)),
        "by_category": dict(Counter(i.category for i in open_inc)),
        "trend": trend,
        "trend_note": "30-day window ending at the latest synthetic incident timestamp.",
        "high_risk_incidents": [incident_summary(i, services) for i in high_risk],
        "ai_quality": {
            "source": "measured" if latest_eval else "none",
            "note": "Measured by the evaluation harness on the synthetic dataset (MOCK MODE measures the deterministic "
                    "pipeline, not LLM quality)." if latest_eval else "No evaluation run yet - run one from Governance.",
            "evaluation_run_id": latest_eval.id if latest_eval else None,
            "evaluated_at": latest_eval.created_at if latest_eval else None,
            "gate_passed": latest_eval.gate_passed if latest_eval else None,
            "metrics": {k: latest_eval.metrics.get(k) for k in (
                "retrieval.recall_at_5", "retrieval.mrr", "citation.coverage", "diagnosis.root_cause_accuracy",
                "safety.policy_compliance", "injection.resistance", "claims.unsupported_rate")} if latest_eval else {},
            "investigations": {
                "completed": sum(1 for r in runs if r.status == InvestigationStatus.COMPLETED),
                "failed": sum(1 for r in runs if r.status == InvestigationStatus.FAILED),
                "degraded": sum(1 for r in runs if r.degraded),
                "median_duration_seconds": round(durations[len(durations) // 2], 2) if durations else None,
            },
        },
        "recent_activity": activity,
        "classification_scope": [c for c in allowed if c in Classification._value2member_map_],
    }
