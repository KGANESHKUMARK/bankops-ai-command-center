from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import ContainerDep, CurrentUser, DbDep, require, run_or_404
from app.models import Approval, InvestigationEvent, InvestigationRun, LLMCall, PolicyDecisionRecord, RetrievalLog, ToolCall
from app.policy.permissions import Permission
from app.services.flags import get_faults
from app.services.metrics import percentile

router = APIRouter(prefix="/observability", tags=["observability"])


def _stats(values: list[float]) -> dict[str, Any]:
    return {"count": len(values), "p50": percentile(values, 50), "p95": percentile(values, 95),
            "max": round(max(values), 2) if values else None}


@router.get("/summary", summary="Request, workflow, agent, tool, model, retrieval and policy metrics")
def summary(db: DbDep, container: ContainerDep,
            current: CurrentUser = Depends(require(Permission.OBSERVABILITY_READ))) -> dict[str, Any]:
    tenant = current.actor.tenant_id
    runs = db.execute(select(InvestigationRun).where(InvestigationRun.tenant_id == tenant)
                      .order_by(InvestigationRun.created_at.desc()).limit(500)).scalars().all()
    run_ids = [r.id for r in runs]
    steps = db.execute(select(InvestigationEvent).where(InvestigationEvent.investigation_id.in_(run_ids),
                                                        InvestigationEvent.event_type.in_(["step_completed", "step_failed"]))).scalars().all()
    by_agent: dict[str, list[float]] = defaultdict(list)
    for s in steps:
        by_agent[s.agent or "unknown"].append(float(s.duration_ms or 0))
    tools = db.execute(select(ToolCall).where(ToolCall.tenant_id == tenant).order_by(ToolCall.created_at.desc()).limit(2000)).scalars().all()
    by_tool: dict[str, list[float]] = defaultdict(list)
    tool_errors: dict[str, int] = defaultdict(int)
    for t in tools:
        by_tool[t.tool_name].append(float(t.duration_ms))
        if t.status != "ok":
            tool_errors[f"{t.tool_name}:{t.error_code}"] += 1
    llm = db.execute(select(LLMCall).where(LLMCall.tenant_id == tenant).order_by(LLMCall.created_at.desc()).limit(2000)).scalars().all()
    retrieval = db.execute(select(RetrievalLog).where(RetrievalLog.tenant_id == tenant)
                           .order_by(RetrievalLog.created_at.desc()).limit(1000)).scalars().all()
    decisions = db.execute(select(PolicyDecisionRecord.decision).where(PolicyDecisionRecord.tenant_id == tenant)).scalars().all()
    approvals = db.execute(select(Approval).where(Approval.tenant_id == tenant)).scalars().all()
    waits = [(a.decided_at - a.created_at).total_seconds() for a in approvals if a.decided_at]
    finished = [r for r in runs if r.completed_at and r.started_at]
    errors = db.execute(select(InvestigationEvent).where(InvestigationEvent.investigation_id.in_(run_ids),
                                                         InvestigationEvent.status.in_(["error", "failed", "timeout", "rejected", "denied"]))
                        .order_by(InvestigationEvent.id.desc()).limit(25)).scalars().all()
    ok_llm = [c for c in llm if c.status == "ok"]
    return {
        "http": container.metrics.summary(),
        "workflow": {
            "runs": len(runs), "by_status": {s: sum(1 for r in runs if r.status == s) for s in {r.status for r in runs}},
            "degraded_runs": sum(1 for r in runs if r.degraded),
            "duration_seconds": _stats([(r.completed_at - r.started_at).total_seconds() for r in finished]),  # type: ignore[operator]
            "failure_rate": round(sum(1 for r in runs if r.status == "failed") / len(runs), 4) if runs else None,
        },
        "agents": {a: _stats(v) for a, v in sorted(by_agent.items())},
        "tools": {t: {**_stats(v), "errors": sum(n for k, n in tool_errors.items() if k.startswith(t + ":"))}
                  for t, v in sorted(by_tool.items())},
        "tool_errors": dict(sorted(tool_errors.items(), key=lambda kv: -kv[1])[:15]),
        "llm": {
            "calls": len(llm), "errors": sum(1 for c in llm if c.status == "error"),
            "skipped": sum(1 for c in llm if c.status == "skipped"),
            "latency_ms": _stats([float(c.latency_ms) for c in ok_llm]),
            "input_tokens": sum(c.input_tokens for c in ok_llm), "output_tokens": sum(c.output_tokens for c in ok_llm),
            "tokens_estimated": any(c.tokens_estimated for c in ok_llm),
            "estimated_cost_usd": round(sum(c.estimated_cost_usd for c in ok_llm), 6),
            "cost_note": "ESTIMATE from configured per-1K-token prices; mock calls cost $0. Token counts are estimated "
                         "(~4 chars/token) when the provider reports no usage.",
            "error_codes": dict(sorted({c.error_code: sum(1 for x in llm if x.error_code == c.error_code)
                                        for c in llm if c.error_code}.items())),
            "mock_calls": sum(1 for c in llm if c.is_mock),
        },
        "retrieval": {
            "queries": len(retrieval), "latency_ms": _stats([float(r.latency_ms) for r in retrieval]),
            "sufficiency_rate": round(sum(1 for r in retrieval if r.sufficient) / len(retrieval), 3) if retrieval else None,
            "errors": sum(1 for r in retrieval if r.error_code),
            "avg_results": round(sum(r.result_count for r in retrieval) / len(retrieval), 2) if retrieval else None,
        },
        "policy": {"decisions": len(decisions), "denials": sum(1 for d in decisions if d == "deny"),
                   "approvals_required": sum(1 for d in decisions if d == "require_approval")},
        "approvals": {"pending": sum(1 for a in approvals if a.status == "pending"),
                      "wait_seconds": _stats(waits)},
        "recent_errors": [{"investigation_id": e.investigation_id, "seq": e.seq, "at": e.created_at, "type": e.event_type,
                           "agent": e.agent, "tool": e.tool, "status": e.status, "message": e.message[:300]} for e in errors],
        "faults": get_faults(db),
        "gateway": container.gateway.status(),
    }


@router.get("/traces/{investigation_id}", summary="Investigation trace: step spans with nested tool and model calls")
def trace(investigation_id: str, db: DbDep,
          current: CurrentUser = Depends(require(Permission.OBSERVABILITY_READ))) -> dict[str, Any]:
    run = run_or_404(db, current.actor, investigation_id)
    events = db.execute(select(InvestigationEvent).where(InvestigationEvent.investigation_id == run.id)
                        .order_by(InvestigationEvent.seq)).scalars().all()
    origin = events[0].created_at if events else run.created_at
    spans: list[dict[str, Any]] = []
    open_spans: dict[str, dict[str, Any]] = {}
    for ev in events:
        offset = (ev.created_at - origin).total_seconds() * 1000
        if ev.event_type == "step_started":
            span: dict[str, Any] = {"name": ev.agent, "kind": "agent_step", "start_ms": round(offset, 1),
                                    "duration_ms": None, "status": "running", "children": []}
            open_spans[ev.agent or ""] = span
            spans.append(span)
        elif ev.event_type in ("step_completed", "step_failed"):
            closing_span = open_spans.pop(ev.agent or "", None)
            if closing_span:
                closing_span.update(duration_ms=ev.duration_ms, status=ev.status)
        elif ev.event_type in ("tool_call", "llm_call", "policy_decision", "action_executed"):
            child = {"name": ev.tool or (ev.payload or {}).get("prompt_id") or ev.event_type, "kind": ev.event_type,
                     "start_ms": round(offset - (ev.duration_ms or 0), 1), "duration_ms": ev.duration_ms,
                     "status": ev.status, "message": ev.message[:300]}
            parent = open_spans.get(ev.agent or "")
            (parent["children"] if parent else spans).append(child)
    return {"investigation_id": run.id, "correlation_id": run.correlation_id, "status": run.status,
            "workflow_version": run.workflow_version, "model_mode": run.model_mode, "spans": spans,
            "totals": {"steps": run.step_count, "tool_calls": run.tool_call_count, "input_tokens": run.input_tokens,
                       "output_tokens": run.output_tokens, "estimated_cost_usd": run.estimated_cost_usd}}
