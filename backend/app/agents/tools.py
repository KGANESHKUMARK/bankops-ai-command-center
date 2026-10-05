"""Typed, allowlisted tool registry and executor.

Every invocation: registry lookup (unknown/prohibited rejected) -> strict argument
validation -> deterministic policy check -> failure-injection check -> execution
with a deadline -> sanitized, structured result -> persisted ToolCall record.
Mutating tools can never be invoked through `invoke`; they only run through the
ActionService after the policy gate and (when required) human approval.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.agents import tool_schemas as ts
from app.agents.simulation import (
    MUTATIONS,
    SimulationError,
    evaluate_resolution,
    get_service,
    health_summary,
)
from app.core.config import Settings
from app.core.context import tool_var
from app.core.logging import get_logger, redact
from app.domain import CLASSIFICATION_RANK, Classification, IncidentStatus, clearance_rank
from app.models import Incident, IncidentEvent, LogEvent, Service, ServiceDependency, ToolCall
from app.policy.catalog import ACTION_CATALOG, PROHIBITED_ACTIONS
from app.policy.engine import Actor, PolicyEngine
from app.rag.injection import neutralize
from app.rag.retrieval import RetrievalError, Retriever
from app.services.flags import fault_enabled

log = get_logger("agents.tools")


class ToolBudgetExceeded(Exception):
    pass


class ToolError(Exception):
    def __init__(self, code: str, message: str, status: str = "error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class ToolContext:
    db: Session
    actor: Actor
    settings: Settings
    retriever: Retriever | None = None
    investigation_id: str | None = None
    agent: str | None = None
    budget: Callable[[], None] | None = None


@dataclass
class ToolResult:
    ok: bool
    tool: str
    data: dict[str, Any] | None
    error_code: str | None
    message: str
    duration_ms: int
    status: str
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    args_model: type[BaseModel]
    handler: Callable[[ToolContext, Any], dict[str, Any]] | None
    mutating: bool = False
    uses_monitoring_api: bool = False
    description: str = field(default="")


# ------------------------------------------------------------------ helpers
def _incident(ctx: ToolContext, incident_id: str) -> Incident:
    inc = ctx.db.get(Incident, incident_id)
    if inc is None or inc.tenant_id != ctx.actor.tenant_id:
        raise ToolError("not_found", "Incident not found.")
    if CLASSIFICATION_RANK[Classification(inc.classification)] > clearance_rank(ctx.actor.role):
        raise ToolError("not_found", "Incident not found.")
    return inc


def _service(ctx: ToolContext, key: str) -> Service:
    try:
        return get_service(ctx.db, ctx.actor.tenant_id, key)
    except SimulationError as exc:
        raise ToolError(exc.code, exc.message) from exc


# ------------------------------------------------------------ read handlers
def _get_incident_details(ctx: ToolContext, a: ts.IncidentArgs) -> dict[str, Any]:
    inc = _incident(ctx, a.incident_id)
    events = ctx.db.execute(
        select(IncidentEvent).where(IncidentEvent.incident_id == inc.id).order_by(IncidentEvent.occurred_at).limit(25)
    ).scalars()
    primary = ctx.db.get(Service, inc.primary_service_id) if inc.primary_service_id else None
    return {
        "incident_id": inc.id,
        "number": inc.number,
        "title": inc.title,
        "category": inc.category,
        "severity": inc.severity,
        "status": inc.status,
        "classification": inc.classification,
        "primary_service": primary.key if primary else None,
        "affected_services": inc.affected_services,
        "impact": inc.impact,
        "detected_at": inc.detected_at.isoformat(),
        "timeline": [{"at": e.occurred_at.isoformat(), "type": e.event_type, "summary": neutralize(e.summary).text}
                     for e in events],
    }


def _get_service_health(ctx: ToolContext, a: ts.ServiceArgs) -> dict[str, Any]:
    svc = _service(ctx, a.service_key)
    return {"service_key": svc.key, "status": svc.status, "summary": health_summary(svc), "metrics": svc.metrics}


def _get_dependencies(ctx: ToolContext, a: ts.ServiceArgs) -> dict[str, Any]:
    svc = _service(ctx, a.service_key)
    rows = ctx.db.execute(
        select(ServiceDependency).where(
            or_(ServiceDependency.service_id == svc.id, ServiceDependency.depends_on_id == svc.id)
        )
    ).scalars()
    by_id = {s.id: s for s in ctx.db.execute(select(Service).where(Service.tenant_id == svc.tenant_id)).scalars()}
    depends_on, dependents = [], []
    for dep in rows:
        if dep.service_id == svc.id:
            other = by_id[dep.depends_on_id]
            depends_on.append({"service": other.key, "status": other.status, "type": dep.dependency_type})
        else:
            other = by_id[dep.service_id]
            dependents.append({"service": other.key, "status": other.status, "type": dep.dependency_type})
    return {"service_key": svc.key, "depends_on": depends_on, "dependents": dependents}


def _get_logs(ctx: ToolContext, a: ts.LogsArgs) -> dict[str, Any]:
    svc = _service(ctx, a.service_key)
    query = select(LogEvent).where(LogEvent.service_id == svc.id)
    if a.level:
        query = query.where(LogEvent.level == a.level)
    rows = ctx.db.execute(query.order_by(LogEvent.ts.desc()).limit(a.limit)).scalars().all()
    lines, flagged = [], 0
    for row in reversed(rows):
        sanitized = neutralize(row.message)  # logs are untrusted input
        flagged += int(sanitized.detected)
        lines.append({"ts": row.ts.isoformat(), "level": row.level, "service": svc.key, "message": sanitized.text})
    return {"service_key": svc.key, "lines": lines, "neutralized_lines": flagged}


def _search_runbooks(ctx: ToolContext, a: ts.SearchArgs) -> dict[str, Any]:
    if ctx.retriever is None:
        raise ToolError("retriever_unavailable", "Retriever not configured.")
    try:
        res = ctx.retriever.search(ctx.db, ctx.actor, a.query, top_k=a.top_k, investigation_id=ctx.investigation_id)
    except RetrievalError as exc:
        raise ToolError(exc.code, "Knowledge retrieval is unavailable.") from exc
    return {
        "query": res.query,
        "sufficient": res.sufficient,
        "reason": res.reason,
        "excluded_unauthorized": res.excluded_unauthorized,
        "top_score": res.top_score,
        "latency_ms": res.latency_ms,
        "results": [r.as_dict() for r in res.results],
    }


def _search_history(ctx: ToolContext, a: ts.HistoryArgs) -> dict[str, Any]:
    inc = _incident(ctx, a.incident_id)
    max_rank = clearance_rank(ctx.actor.role)
    allowed = [c.value for c, r in CLASSIFICATION_RANK.items() if r <= max_rank]
    rows = ctx.db.execute(
        select(Incident)
        .where(
            Incident.tenant_id == ctx.actor.tenant_id,
            Incident.id != inc.id,
            Incident.category == inc.category,
            Incident.status.in_([IncidentStatus.RESOLVED.value, IncidentStatus.CLOSED.value]),
            Incident.classification.in_(allowed),
            Incident.resolution_summary.is_not(None),
        )
        .order_by(Incident.detected_at.desc())
        .limit(a.limit)
    ).scalars()
    return {
        "incidents": [
            {"incident_id": r.id, "number": r.number, "title": r.title, "detected_at": r.detected_at.isoformat(),
             "classification": r.classification, "resolution_summary": neutralize(r.resolution_summary or "").text}
            for r in rows
        ]
    }


def _queue_metrics(ctx: ToolContext, a: ts.QueueArgs) -> dict[str, Any]:
    mq = _service(ctx, "ibm-mq")
    q = dict((mq.metrics.get("queues") or {}).get(a.queue_name) or {})
    if not q:
        raise ToolError("not_found", "Queue not found.")
    ratio = q.get("depth", 0) / max(1, q.get("max_depth", 1))
    q["fill_ratio"] = round(ratio, 3)
    q["assessment"] = f"queue depth approaching max ({ratio:.0%})" if ratio >= 0.9 else f"queue depth at {ratio:.0%}"
    return {"queue_manager": mq.metrics.get("queue_manager"), "queue_name": a.queue_name, **q}


def _stream_metrics(ctx: ToolContext, a: ts.StreamArgs) -> dict[str, Any]:
    if a.stream == "cg-transaction-enricher":
        m = dict(_service(ctx, "transaction-enricher").metrics)
        lags = list((m.get("lag_by_partition") or {}).values()) or [0]
        avg = sum(lags) / len(lags)
        notes = ["throughput below ingest" if m.get("throughput_per_s", 0) < m.get("ingest_rate_per_s", 0) else "throughput above ingest",
                 "lag evenly distributed" if max(lags) <= 1.5 * max(avg, 1) else "lag concentrated on few partitions"]
        return {"stream": a.stream, **m, "assessment": notes}
    if a.stream == "card-transactions":
        kafka = _service(ctx, "kafka-cluster").metrics
        return {"stream": a.stream, "broker_health": kafka.get("broker_health"),
                **(kafka.get("topics", {}).get("card-transactions") or {})}
    if a.stream == "risk-events":
        reg = _service(ctx, "schema-registry").metrics
        return {"stream": a.stream, **(reg.get("subjects", {}).get("risk-events-value") or {})}
    if a.stream == "flink-risk-aggregator":
        return {"stream": a.stream, **_service(ctx, "flink-risk-aggregator").metrics}
    dedup = _service(ctx, "event-dedup-service").metrics
    publisher = _service(ctx, "payments-event-publisher").metrics
    return {"stream": a.stream, "dedup": dedup, "publisher": publisher}


def _validate_template(ctx: ToolContext, a: ts.TemplateArgs) -> dict[str, Any]:
    store = _service(ctx, "template-store")
    tpl = (store.metrics.get("templates") or {}).get(a.template_id)
    if tpl is None:
        return {"template_id": a.template_id, "valid": False, "status": "unregistered"}
    return {"template_id": a.template_id, "valid": tpl.get("status") == "active", "status": tpl.get("status"),
            "version": tpl.get("version"), "last_approved_version": tpl.get("last_approved_version")}


def _schema_compat(ctx: ToolContext, a: ts.SchemaCompatArgs) -> dict[str, Any]:
    reg = _service(ctx, "schema-registry")
    versions = reg.metrics.get("subjects", {}).get(a.subject, {}).get("versions", {})
    writer, reader = versions.get(str(a.writer_version)), versions.get(str(a.reader_version))
    if writer is None or reader is None:
        raise ToolError("not_found", "Schema version not found.")
    issues = [
        f"{name}: reader {rtype} vs writer {writer['fields'].get(name, 'missing')}"
        for name, rtype in reader["fields"].items()
        if writer["fields"].get(name) != rtype
    ]
    return {"subject": a.subject, "writer_version": a.writer_version, "reader_version": a.reader_version,
            "compatible": not issues, "incompatibilities": issues,
            "registry_compatibility_mode": reg.metrics["subjects"][a.subject].get("compatibility")}


def _verify_health(ctx: ToolContext, a: ts.ServiceArgs) -> dict[str, Any]:
    svc = _service(ctx, a.service_key)
    return {"service_key": svc.key, "status": svc.status, "healthy": svc.status == "healthy", "summary": health_summary(svc)}


def _verify_resolution(ctx: ToolContext, a: ts.IncidentArgs) -> dict[str, Any]:
    return evaluate_resolution(ctx.db, _incident(ctx, a.incident_id))


READ_TOOLS: list[ToolSpec] = [
    ToolSpec("get_incident_details", ts.IncidentArgs, _get_incident_details),
    ToolSpec("get_service_health", ts.ServiceArgs, _get_service_health, uses_monitoring_api=True),
    ToolSpec("get_service_dependencies", ts.ServiceArgs, _get_dependencies, uses_monitoring_api=True),
    ToolSpec("get_recent_synthetic_logs", ts.LogsArgs, _get_logs, uses_monitoring_api=True),
    ToolSpec("search_authorized_runbooks", ts.SearchArgs, _search_runbooks),
    ToolSpec("search_incident_history", ts.HistoryArgs, _search_history),
    ToolSpec("inspect_synthetic_queue_metrics", ts.QueueArgs, _queue_metrics, uses_monitoring_api=True),
    ToolSpec("inspect_synthetic_stream_metrics", ts.StreamArgs, _stream_metrics, uses_monitoring_api=True),
    ToolSpec("validate_synthetic_document_template", ts.TemplateArgs, _validate_template),
    ToolSpec("validate_synthetic_schema_compatibility", ts.SchemaCompatArgs, _schema_compat),
    ToolSpec("verify_service_health", ts.ServiceArgs, _verify_health, uses_monitoring_api=True),
    ToolSpec("verify_incident_resolution", ts.IncidentArgs, _verify_resolution),
]

MUTATING_ARGS: dict[str, type[BaseModel]] = {
    "simulate_restart_document_renderer": ts.RestartRendererArgs,
    "simulate_reprocess_failed_statement": ts.ReprocessStatementArgs,
    "simulate_restore_missing_template": ts.RestoreTemplateArgs,
    "simulate_restart_mq_consumer": ts.RestartMqConsumerArgs,
    "simulate_scale_consumer_group": ts.ScaleConsumerArgs,
    "simulate_replay_dead_letter_events": ts.ReplayDlqArgs,
    "simulate_restart_flink_job_from_checkpoint": ts.RestartFlinkArgs,
    "simulate_rerun_snowflake_pipeline": ts.RerunSnowflakeArgs,
    "simulate_rerun_data_quality_checks": ts.RerunDqArgs,
}

REGISTRY: dict[str, ToolSpec] = {t.name: t for t in READ_TOOLS} | {
    name: ToolSpec(name, model, None, mutating=True) for name, model in MUTATING_ARGS.items()
}
assert set(REGISTRY) == set(ACTION_CATALOG), "tool registry and risk catalog must match exactly"
assert set(MUTATING_ARGS) == set(MUTATIONS), "every mutating tool needs a simulation"


def sanitize_validation_error(exc: ValidationError) -> list[dict[str, str]]:
    """Field locations and error types only - never echo submitted values."""
    return [{"loc": ".".join(str(p) for p in e["loc"]), "type": e["type"]} for e in exc.errors()][:10]


class ToolExecutor:
    def __init__(self, settings: Settings, policy: PolicyEngine) -> None:
        self.settings = settings
        self.policy = policy

    def validate_args(self, tool_name: str, raw_args: dict[str, Any]) -> BaseModel:
        if tool_name in PROHIBITED_ACTIONS:
            raise ToolError("prohibited_tool", f"'{tool_name}' is prohibited.", status="rejected")
        spec = REGISTRY.get(tool_name)
        if spec is None:
            raise ToolError("unknown_tool", f"'{tool_name}' is not an allowlisted tool.", status="rejected")
        if not isinstance(raw_args, dict):
            raise ToolError("invalid_arguments", "Arguments must be an object.", status="rejected")
        try:
            return spec.args_model.model_validate(raw_args)
        except ValidationError as exc:
            raise ToolError("invalid_arguments", f"Invalid arguments: {sanitize_validation_error(exc)}", status="rejected") from exc

    def _record(self, ctx: ToolContext, tool_name: str, args: dict[str, Any], result: ToolResult) -> None:
        summary: dict[str, Any] = {}
        if result.data:
            summary = {k: (v if isinstance(v, bool | int | float) or v is None else str(v)[:120])
                       for k, v in list(result.data.items())[:8] if not isinstance(v, dict | list)}
        rec = ToolCall(
            tenant_id=ctx.actor.tenant_id,
            investigation_id=ctx.investigation_id,
            tool_name=tool_name[:80],
            agent=ctx.agent,
            args=redact(args),
            status=result.status,
            error_code=result.error_code,
            duration_ms=result.duration_ms,
            result_summary=summary,
            requested_by=ctx.actor.user_id,
        )
        ctx.db.add(rec)
        ctx.db.flush()
        result.tool_call_id = rec.id

    def invoke(self, ctx: ToolContext, tool_name: str, raw_args: dict[str, Any], *, incident: Incident | None = None) -> ToolResult:
        """Invoke a read-only tool. Raises ToolBudgetExceeded when the workflow budget is exhausted."""
        if ctx.budget is not None:
            ctx.budget()
        started = time.perf_counter()
        token = tool_var.set(tool_name)
        try:
            try:
                args = self.validate_args(tool_name, raw_args)
                spec = REGISTRY[tool_name]
                if spec.mutating:
                    raise ToolError("requires_policy_gate", "Mutating tools only run via approved actions.", status="denied")
                decision = self.policy.evaluate_action(
                    ctx.actor,
                    tool_name=tool_name,
                    target_resource=None,
                    incident_tenant_id=incident.tenant_id if incident else None,
                    incident_status=incident.status if incident else None,
                    incident_classification=incident.classification if incident else None,
                )
                if decision.decision != "allow":
                    raise ToolError("policy_denied", decision.explanation, status="denied")
                if spec.uses_monitoring_api and fault_enabled(ctx.db, "downstream_outage"):
                    raise ToolError("downstream_unavailable_injected", "Synthetic monitoring API unavailable (injected fault).")
                assert spec.handler is not None
                data = spec.handler(ctx, args)
                elapsed = time.perf_counter() - started
                if elapsed > self.settings.tool_timeout_seconds:
                    raise ToolError("tool_timeout", f"Tool exceeded {self.settings.tool_timeout_seconds}s deadline.", status="timeout")
                result = ToolResult(True, tool_name, data, None, "ok", int(elapsed * 1000), "ok")
            except ToolError as exc:
                result = ToolResult(False, tool_name, None, exc.code, exc.message, int((time.perf_counter() - started) * 1000), exc.status)
            self._record(ctx, tool_name, raw_args if isinstance(raw_args, dict) else {}, result)
            log.info("tool call", extra={"status": result.status, "duration_ms": result.duration_ms, "error_code": result.error_code})
            return result
        finally:
            tool_var.reset(token)
