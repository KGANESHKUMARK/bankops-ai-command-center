"""Synthetic environment simulation: read models, safe mutations, rollback and verification.

Mutations only touch seeded demo state (`services.metrics/status`, synthetic logs
and incident timeline) inside the caller's transaction. Nothing here performs I/O
outside the application database.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.base import utcnow
from app.domain import IncidentStatus, ServiceStatus
from app.models import Incident, IncidentEvent, LogEvent, Service


class SimulationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def get_service(db: Session, tenant_id: str, key: str) -> Service:
    svc = db.execute(select(Service).where(Service.tenant_id == tenant_id, Service.key == key)).scalar_one_or_none()
    if svc is None:
        raise SimulationError("unknown_service", f"Service '{key}' does not exist in this tenant.")
    return svc


def _scalar_pairs(metrics: dict[str, Any], limit: int = 8) -> list[str]:
    pairs = []
    for k, v in metrics.items():
        if isinstance(v, bool | int | float | str) and v is not None:
            pairs.append(f"{k}={v}")
        if len(pairs) >= limit:
            break
    return pairs


def health_summary(svc: Service) -> str:
    m = svc.metrics or {}
    parts = [f"{svc.key} is {svc.status}"]
    if "instances_total" in m:
        parts.append(f"{m.get('instances_ready', 0)}/{m['instances_total']} instances ready")
    parts.extend(_scalar_pairs({k: v for k, v in m.items() if k not in ("instances_ready", "instances_total")}, 6))
    return "; ".join(parts)


def flatten_text(obj: Any, prefix: str = "") -> list[str]:
    """Flatten nested observations into lowercase `key=value` tokens for signal matching."""
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict | list):
                out.extend(flatten_text(v, str(k)))
            else:
                out.append(f"{k}={v}".lower())
    elif isinstance(obj, list):
        for item in obj:
            out.extend(flatten_text(item, prefix))
    elif obj is not None:
        out.append(str(obj).lower())
    return out


def _log(db: Session, svc: Service, level: str, message: str, incident_id: str | None = None) -> None:
    db.add(
        LogEvent(
            tenant_id=svc.tenant_id,
            service_id=svc.id,
            incident_id=incident_id,
            ts=utcnow(),
            level=level,
            message=message,
            attributes={"synthetic": True, "simulated_action": True},
        )
    )


def _touch(svc: Service) -> None:
    flag_modified(svc, "metrics")
    svc.updated_at = utcnow()


def snapshot(services: list[Service]) -> dict[str, Any]:
    return {s.key: {"status": s.status, "metrics": copy.deepcopy(s.metrics)} for s in services}


def restore_snapshot(db: Session, tenant_id: str, snap: dict[str, Any]) -> list[str]:
    restored = []
    for key, state in snap.items():
        svc = get_service(db, tenant_id, key)
        svc.status = state["status"]
        svc.metrics = copy.deepcopy(state["metrics"])
        _touch(svc)
        _log(db, svc, "WARN", f"[SIMULATED] Rollback restored previous state of {key}.")
        restored.append(key)
    return restored


# --------------------------------------------------------------------- mutations
@dataclass(frozen=True)
class Mutation:
    affected: Callable[[Any], list[str]]
    preconditions: Callable[[Session, str, Any], list[dict[str, Any]]]
    apply: Callable[[Session, str, Any, str], dict[str, Any]]


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), "detail": detail}


def _pre_restart_renderer(db: Session, tenant: str, args: Any) -> list[dict[str, Any]]:
    svc = get_service(db, tenant, args.service_key)
    return [_check("renderer_not_healthy", svc.status != ServiceStatus.HEALTHY,
                   f"document-renderer status is {svc.status} (restart only when unhealthy)")]


def _apply_restart_renderer(db: Session, tenant: str, args: Any, action_id: str) -> dict[str, Any]:
    svc = get_service(db, tenant, "document-renderer")
    m = svc.metrics
    m.update(instances_ready=m.get("instances_total", 3), error_rate=0.0, p95_latency_ms=420, heap_used_pct=38,
             failure_mode=None, last_restart=utcnow().isoformat())
    m["connection_pool"] = {"active": 12, "max": 200}
    svc.status = ServiceStatus.HEALTHY.value
    _touch(svc)
    _log(db, svc, "INFO", f"[SIMULATED] Rolling restart completed by action {action_id[:8]}: "
         f"{m['instances_ready']}/{m['instances_total']} instances ready.")
    gen = get_service(db, tenant, "statement-generator")
    gen.metrics["render_client_circuit"] = "closed"
    _touch(gen)
    _log(db, gen, "INFO", "[SIMULATED] RenderClient circuit breaker CLOSED; document-renderer reachable.")
    return {"service": "document-renderer", "new_status": "healthy", "instances_ready": m["instances_ready"]}


def _pre_reprocess(db: Session, tenant: str, args: Any) -> list[dict[str, Any]]:
    svc = get_service(db, tenant, args.service_key)
    batch = (svc.metrics.get("batches") or {}).get(args.batch_id)
    checks = [_check("batch_exists_and_failed", batch is not None and batch.get("status") == "failed",
                     f"batch {args.batch_id} status is {batch.get('status') if batch else 'missing'}")]
    if batch:
        checks.append(_check("within_max_documents", batch.get("documents_total", 0) <= args.max_documents,
                             f"{batch.get('documents_total', 0)} documents <= max {args.max_documents}"))
    if args.service_key == "statement-generator":
        dep = get_service(db, tenant, "document-renderer")
        checks.append(_check("dependency_document_renderer_healthy", dep.status == ServiceStatus.HEALTHY,
                             f"document-renderer is {dep.status}"))
    else:
        store = get_service(db, tenant, "template-store")
        tpl = (store.metrics.get("templates") or {}).get((batch or {}).get("template_id", ""), {})
        checks.append(_check("template_active", tpl.get("status") == "active",
                             f"template {(batch or {}).get('template_id')} is {tpl.get('status', 'missing')}"))
    return checks


def _apply_reprocess(db: Session, tenant: str, args: Any, action_id: str) -> dict[str, Any]:
    svc = get_service(db, tenant, args.service_key)
    batch = svc.metrics["batches"][args.batch_id]
    batch.update(status="completed", documents_failed=0, documents_rendered=batch.get("documents_total", 0),
                 completed_at=utcnow().isoformat())
    if all(b.get("status") == "completed" for b in svc.metrics["batches"].values()):
        svc.status = ServiceStatus.HEALTHY.value
        svc.metrics.update(error_rate=0.0, queue_depth=0)
    _touch(svc)
    _log(db, svc, "INFO", f"[SIMULATED] Batch {args.batch_id} reprocessed by action {action_id[:8]}: "
         f"{batch['documents_rendered']} documents rendered.")
    return {"batch_id": args.batch_id, "batch_status": "completed", "service_status": svc.status}


def _pre_restore_template(db: Session, tenant: str, args: Any) -> list[dict[str, Any]]:
    store = get_service(db, tenant, "template-store")
    tpl = (store.metrics.get("templates") or {}).get(args.template_id)
    return [
        _check("template_missing", tpl is not None and tpl.get("status") == "missing",
               f"template status is {tpl.get('status') if tpl else 'unknown (not registered)'}"),
        _check("restore_version_is_last_approved",
               tpl is not None and tpl.get("last_approved_version") == args.restore_from_version,
               f"last approved version is {tpl.get('last_approved_version') if tpl else 'n/a'}"),
    ]


def _apply_restore_template(db: Session, tenant: str, args: Any, action_id: str) -> dict[str, Any]:
    store = get_service(db, tenant, "template-store")
    tpl = store.metrics["templates"][args.template_id]
    tpl.update(status="active", version=args.restore_from_version, restored_at=utcnow().isoformat())
    if all(t.get("status") == "active" for t in store.metrics["templates"].values()):
        store.status = ServiceStatus.HEALTHY.value
    _touch(store)
    _log(db, store, "INFO", f"[SIMULATED] Template {args.template_id} restored to {args.restore_from_version} "
         f"by action {action_id[:8]}.")
    return {"template_id": args.template_id, "status": "active", "version": args.restore_from_version}


def _pre_restart_mq(db: Session, tenant: str, args: Any) -> list[dict[str, Any]]:
    svc = get_service(db, tenant, args.consumer)
    return [
        _check("consumer_not_running", svc.status != ServiceStatus.HEALTHY, f"consumer status is {svc.status}"),
        _check("channel_matches", svc.metrics.get("channel") == args.channel, f"configured channel {svc.metrics.get('channel')}"),
    ]


def _apply_restart_mq(db: Session, tenant: str, args: Any, action_id: str) -> dict[str, Any]:
    svc = get_service(db, tenant, args.consumer)
    svc.metrics.update(channel_state="RUNNING", last_error=None)
    svc.status = ServiceStatus.HEALTHY.value
    _touch(svc)
    mq = get_service(db, tenant, "ibm-mq")
    q = mq.metrics["queues"]["PAYMENT.SETTLEMENT.IN"]
    q.update(depth=1200, open_input_count=1, oldest_message_age_s=45)
    mq.status = ServiceStatus.HEALTHY.value
    _touch(mq)
    _log(db, svc, "INFO", f"[SIMULATED] Channel {args.channel} restarted by action {action_id[:8]}; consumer connected.")
    _log(db, mq, "INFO", "[SIMULATED] PAYMENT.SETTLEMENT.IN draining: depth 1200, open_input_count=1.")
    return {"consumer": args.consumer, "channel_state": "RUNNING", "queue_depth": 1200}


def _pre_scale(db: Session, tenant: str, args: Any) -> list[dict[str, Any]]:
    svc = get_service(db, tenant, "transaction-enricher")
    m = svc.metrics
    limit = min(int(m.get("max_replicas", 12)), int(m.get("partitions", 12)))
    return [
        _check("scale_up_only", args.target_replicas > int(m.get("replicas", 0)),
               f"current replicas {m.get('replicas')} -> target {args.target_replicas}"),
        _check("within_partition_limit", args.target_replicas <= limit, f"limit {limit} (partitions/max replicas)"),
    ]


def _apply_scale(db: Session, tenant: str, args: Any, action_id: str) -> dict[str, Any]:
    svc = get_service(db, tenant, "transaction-enricher")
    m = svc.metrics
    per_replica = int(m.get("per_replica_throughput_per_s", 1000))
    m.update(replicas=args.target_replicas, throughput_per_s=per_replica * args.target_replicas)
    if m["throughput_per_s"] > int(m.get("ingest_rate_per_s", 0)):
        m.update(lag_total=38000, lag_trend="draining (simulated projection)")
        svc.status = ServiceStatus.HEALTHY.value
    _touch(svc)
    _log(db, svc, "INFO", f"[SIMULATED] Consumer group scaled to {args.target_replicas} replicas by action "
         f"{action_id[:8]}; throughput {m['throughput_per_s']}/s vs ingest {m.get('ingest_rate_per_s')}/s.")
    return {"replicas": args.target_replicas, "throughput_per_s": m["throughput_per_s"], "lag_total": m["lag_total"]}


def _pre_replay(db: Session, tenant: str, args: Any) -> list[dict[str, Any]]:
    if args.source == "card-transactions.dlq":
        svc = get_service(db, tenant, "transaction-enricher")
        depth = int((svc.metrics.get("dlq") or {}).get(args.source, 0))
        return [
            _check("dlq_not_empty", depth > 0, f"{depth} events in {args.source}"),
            _check("lag_recovered_before_replay", int(svc.metrics.get("lag_total", 0)) < 100000,
                   f"consumer lag {svc.metrics.get('lag_total')} must be < 100000 before replay"),
            _check("bounded_replay", args.max_events <= max(depth, 1), f"max_events {args.max_events} <= depth {depth}"),
        ]
    mq = get_service(db, tenant, "ibm-mq")
    depth = int(mq.metrics["queues"]["PAYMENT.SETTLEMENT.DLQ"]["depth"])
    consumer = get_service(db, tenant, "mq-settlement-consumer")
    return [
        _check("dlq_not_empty", depth > 0, f"{depth} messages in DLQ"),
        _check("consumer_running", consumer.status == ServiceStatus.HEALTHY, f"consumer is {consumer.status}"),
    ]


def _apply_replay(db: Session, tenant: str, args: Any, action_id: str) -> dict[str, Any]:
    if args.source == "card-transactions.dlq":
        svc = get_service(db, tenant, "transaction-enricher")
        depth = int(svc.metrics["dlq"][args.source])
        replayed = min(depth, args.max_events)
        svc.metrics["dlq"][args.source] = depth - replayed
    else:
        svc = get_service(db, tenant, "ibm-mq")
        q = svc.metrics["queues"]["PAYMENT.SETTLEMENT.DLQ"]
        replayed = min(int(q["depth"]), args.max_events)
        q["depth"] = int(q["depth"]) - replayed
    _touch(svc)
    _log(db, svc, "WARN", f"[SIMULATED] Replayed {replayed} dead-letter events from {args.source} by action "
         f"{action_id[:8]} (idempotency check enforced).")
    return {"source": args.source, "replayed": replayed}


def _pre_flink(db: Session, tenant: str, args: Any) -> list[dict[str, Any]]:
    job = get_service(db, tenant, args.job_name)
    reg = get_service(db, tenant, "schema-registry")
    versions = (reg.metrics.get("subjects", {}).get("risk-events-value", {}).get("versions") or {})
    return [
        _check("job_failed", job.metrics.get("job_state") in ("FAILED", "RESTARTING"), f"job_state={job.metrics.get('job_state')}"),
        _check("pinned_version_exists", str(args.pin_reader_schema_version) in versions,
               f"schema versions available: {', '.join(sorted(versions))}"),
        _check("pinned_version_matches_state", args.pin_reader_schema_version == job.metrics.get("state_schema_version"),
               f"checkpoint state schema version is {job.metrics.get('state_schema_version')}"),
    ]


def _apply_flink(db: Session, tenant: str, args: Any, action_id: str) -> dict[str, Any]:
    job = get_service(db, tenant, args.job_name)
    job.metrics.update(job_state="RUNNING", pinned_reader_schema_version=args.pin_reader_schema_version,
                       restarts_since_recovery=0, quarantined_incompatible_events=0, exception=None,
                       restored_from=job.metrics.get("last_checkpoint"))
    job.status = ServiceStatus.DEGRADED.value
    _touch(job)
    _log(db, job, "INFO", f"[SIMULATED] Job restored from {job.metrics.get('last_checkpoint')} with reader schema "
         f"v{args.pin_reader_schema_version} pinned by action {action_id[:8]}; incompatible events quarantined.")
    return {"job_state": "RUNNING", "pinned_reader_schema_version": args.pin_reader_schema_version,
            "note": "Schema registry unchanged; producer fix required via change management."}


def _pre_snowflake(db: Session, tenant: str, args: Any) -> list[dict[str, Any]]:
    svc = get_service(db, tenant, "snowflake-ingestion")
    dw = get_service(db, tenant, "snowflake-dw")
    return [
        _check("task_suspended", svc.metrics.get("task_state") == "SUSPENDED", f"task_state={svc.metrics.get('task_state')}"),
        _check("warehouse_available", dw.status == ServiceStatus.HEALTHY, f"snowflake-dw is {dw.status}"),
    ]


def _apply_snowflake(db: Session, tenant: str, args: Any, action_id: str) -> dict[str, Any]:
    svc = get_service(db, tenant, "snowflake-ingestion")
    svc.metrics.update(task_state="STARTED", freshness_lag_minutes=12, failed_loads=0, last_success=utcnow().isoformat())
    svc.status = ServiceStatus.HEALTHY.value
    _touch(svc)
    _log(db, svc, "INFO", f"[SIMULATED] Task {args.task} resumed and re-run by action {action_id[:8]}; freshness 12m.")
    return {"task_state": "STARTED", "freshness_lag_minutes": 12}


def _pre_dq(db: Session, tenant: str, args: Any) -> list[dict[str, Any]]:
    svc = get_service(db, tenant, "reporting-dq-validator")
    return [_check("suite_registered", svc.metrics.get("suite") == args.suite, f"suite={svc.metrics.get('suite')}")]


def _apply_dq(db: Session, tenant: str, args: Any, action_id: str) -> dict[str, Any]:
    svc = get_service(db, tenant, "reporting-dq-validator")
    svc.metrics["last_run"] = utcnow().isoformat()
    if svc.metrics.get("upstream_fixed"):
        svc.metrics.update(failed_checks=[], failed_rows=0)
    _touch(svc)
    failed = svc.metrics.get("failed_checks", [])
    _log(db, svc, "WARN" if failed else "INFO", f"[SIMULATED] DQ suite {args.suite} re-run by action {action_id[:8]}: "
         f"{len(failed)} failing check(s).")
    return {"suite": args.suite, "failed_checks": failed, "failed_rows": svc.metrics.get("failed_rows", 0)}


MUTATIONS: dict[str, Mutation] = {
    "simulate_restart_document_renderer": Mutation(
        lambda a: ["document-renderer", "statement-generator"], _pre_restart_renderer, _apply_restart_renderer),
    "simulate_reprocess_failed_statement": Mutation(lambda a: [a.service_key], _pre_reprocess, _apply_reprocess),
    "simulate_restore_missing_template": Mutation(lambda a: ["template-store"], _pre_restore_template, _apply_restore_template),
    "simulate_restart_mq_consumer": Mutation(lambda a: [a.consumer, "ibm-mq"], _pre_restart_mq, _apply_restart_mq),
    "simulate_scale_consumer_group": Mutation(lambda a: ["transaction-enricher"], _pre_scale, _apply_scale),
    "simulate_replay_dead_letter_events": Mutation(
        lambda a: ["transaction-enricher"] if a.source == "card-transactions.dlq" else ["ibm-mq"], _pre_replay, _apply_replay),
    "simulate_restart_flink_job_from_checkpoint": Mutation(lambda a: [a.job_name], _pre_flink, _apply_flink),
    "simulate_rerun_snowflake_pipeline": Mutation(lambda a: ["snowflake-ingestion"], _pre_snowflake, _apply_snowflake),
    "simulate_rerun_data_quality_checks": Mutation(lambda a: ["reporting-dq-validator"], _pre_dq, _apply_dq),
}

TARGET_OF: dict[str, Callable[[Any], str]] = {
    "simulate_restart_document_renderer": lambda a: a.service_key,
    "simulate_reprocess_failed_statement": lambda a: a.service_key,
    "simulate_restore_missing_template": lambda a: "template-store",
    "simulate_restart_mq_consumer": lambda a: a.consumer,
    "simulate_scale_consumer_group": lambda a: "transaction-enricher",
    "simulate_replay_dead_letter_events": lambda a: (
        "transaction-enricher" if a.source == "card-transactions.dlq" else "mq-settlement-consumer"),
    "simulate_restart_flink_job_from_checkpoint": lambda a: a.job_name,
    "simulate_rerun_snowflake_pipeline": lambda a: "snowflake-ingestion",
    "simulate_rerun_data_quality_checks": lambda a: "reporting-dq-validator",
}


# ------------------------------------------------------------------ verification
def evaluate_resolution(db: Session, incident: Incident) -> dict[str, Any]:
    """Deterministically evaluate the incident's seeded resolution criteria against current state."""
    tenant = incident.tenant_id
    crit = incident.resolution_criteria or {}
    checks: list[dict[str, Any]] = []

    def svc(key: str) -> Service | None:
        try:
            return get_service(db, tenant, key)
        except SimulationError:
            return None

    for key in crit.get("services_healthy", []):
        s = svc(key)
        checks.append({"name": f"{key} healthy", "passed": bool(s and s.status == ServiceStatus.HEALTHY),
                       "detail": f"status={s.status if s else 'unknown'}"})
    for b in crit.get("batches_completed", []):
        s = svc(b["service"])
        status = ((s.metrics.get("batches") or {}).get(b["batch_id"], {}) if s else {}).get("status", "unknown")
        checks.append({"name": f"batch {b['batch_id']} completed", "passed": status == "completed", "detail": f"status={status}"})
    for tpl_id in crit.get("templates_active", []):
        s = svc("template-store")
        status = ((s.metrics.get("templates") or {}).get(tpl_id, {}) if s else {}).get("status", "unknown")
        checks.append({"name": f"template {tpl_id} active", "passed": status == "active", "detail": f"status={status}"})
    if c := crit.get("consumer_lag_below"):
        s = svc(c["service"])
        lag = int(s.metrics.get("lag_total", 0)) if s else -1
        checks.append({"name": f"consumer lag < {c['max_lag']}", "passed": s is not None and lag < c["max_lag"], "detail": f"lag_total={lag}"})
    if key := crit.get("flink_job_running"):
        s = svc(key)
        state = s.metrics.get("job_state") if s else "unknown"
        checks.append({"name": f"{key} job RUNNING", "passed": state == "RUNNING", "detail": f"job_state={state}"})
    if c := crit.get("queue_depth_below"):
        s = svc("ibm-mq")
        depth = int(s.metrics["queues"][c["queue"]]["depth"]) if s else -1
        checks.append({"name": f"{c['queue']} depth < {c['max_depth']}",
                       "passed": s is not None and depth < c["max_depth"], "detail": f"depth={depth}"})
    if c := crit.get("pipeline_task_state"):
        s = svc(c["service"])
        state = s.metrics.get("task_state") if s else "unknown"
        checks.append({"name": f"task state {c['state']}", "passed": state == c["state"], "detail": f"task_state={state}"})
    if c := crit.get("freshness_below"):
        s = svc(c["service"])
        lag = int(s.metrics.get("freshness_lag_minutes", 10**6)) if s else 10**6
        checks.append({"name": f"freshness < {c['minutes']}m", "passed": lag < c["minutes"], "detail": f"freshness_lag_minutes={lag}"})
    if c := crit.get("duplicate_ratio_below"):
        s = svc(c["service"])
        ratio = float(s.metrics.get("duplicate_ratio", 1.0)) if s else 1.0
        checks.append({"name": f"duplicate ratio < {c['max_ratio']}", "passed": ratio < c["max_ratio"], "detail": f"duplicate_ratio={ratio}"})
    if c := crit.get("dq_checks_passing"):
        s = svc(c["service"])
        failed = s.metrics.get("failed_checks", ["unknown"]) if s else ["unknown"]
        checks.append({"name": f"DQ suite {c['suite']} passing", "passed": not failed, "detail": f"failed_checks={len(failed)}"})

    passed = sum(1 for c in checks if c["passed"])
    if not checks:
        status = "unresolved"
    elif passed == len(checks):
        status = "resolved"
    elif passed > 0:
        status = "partially_resolved"
    else:
        status = "unresolved"
    return {"status": status, "checks": checks, "passed": passed, "total": len(checks)}


def mark_incident(db: Session, incident: Incident, status: IncidentStatus, summary: str, source: str = "workflow") -> None:
    if incident.status == status.value:
        return
    incident.status = status.value
    incident.updated_at = utcnow()
    if status == IncidentStatus.RESOLVED:
        incident.resolved_at = utcnow()
    db.add(IncidentEvent(incident_id=incident.id, tenant_id=incident.tenant_id, occurred_at=utcnow(),
                         event_type="status_change", source=source, summary=summary, details={"status": status.value}))
