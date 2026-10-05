"""Deterministic failure-pattern library used by the MOCK provider.

This is NOT model inference. Hypotheses are scored from signals that actually
appear in tool observations and retrieved evidence; plans are templates bound to
observed parameters. Output is always labeled MOCK MODE.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Pattern:
    root_cause: str
    title: str
    description: str
    signals: tuple[str, ...]
    contra: tuple[str, ...] = ()
    further_checks: tuple[str, ...] = field(default_factory=tuple)


LIBRARY: dict[str, list[Pattern]] = {
    "statement_generation": [
        Pattern(
            "renderer_outage",
            "Downstream document-renderer service unavailable",
            "Statement jobs fail because the document-renderer dependency is down (heap exhaustion, 0 ready "
            "instances) and returns 503 to render requests.",
            ("503 service unavailable", "renderer_unavailable", "outofmemoryerror", "0/3 instances ready",
             "connection pool exhausted", "document-renderer is down", "circuit breaker open"),
            ("document-renderer is healthy",),
            ("Confirm renderer heap usage trend before restart", "Check renderer deployment history (synthetic)"),
        ),
        Pattern(
            "missing_template",
            "Required statement template missing from template-store",
            "Rendering fails because the configured document template version cannot be found.",
            ("templatenotfoundexception", "template missing", "status=missing", "not found in template-store"),
            ("valid=true",),
            ("Validate template registry entries for the batch", "Check the last template publication job"),
        ),
        Pattern(
            "upstream_data_delay",
            "Upstream account extract delayed",
            "Statement generation waits on a late upstream data extract.",
            ("extract delayed", "extract late", "waiting for upstream extract"),
            ("received on time",),
            ("Confirm extract arrival time with the scheduler",),
        ),
    ],
    "kafka_consumer_lag": [
        Pattern(
            "consumer_processing_bottleneck",
            "Consumer processing bottleneck (slow enrichment lookups)",
            "Per-message processing time rose ~8x due to slow customer-profile-cache lookups, so consumer "
            "throughput fell below the ingest rate and lag accumulates evenly across partitions.",
            ("processing_ms_p99=820", "enrichment lookup", "customer-profile-cache", "throughput below ingest",
             "lag evenly distributed", "timeout budget"),
            ("processing time normal",),
            ("Profile enrichment lookup latency", "Confirm consumer idempotency before any replay"),
        ),
        Pattern(
            "partition_skew",
            "Hot partition / key skew",
            "Lag concentrated on a small number of partitions due to key skew.",
            ("partition skew", "hot partition", "lag concentrated"),
            ("lag evenly distributed",),
            ("Inspect per-partition lag distribution",),
        ),
        Pattern(
            "broker_degradation",
            "Kafka broker degradation",
            "Broker-side issues (under-replicated partitions) slow fetches.",
            ("under-replicated", "isr shrink", "broker unavailable"),
            ("broker_health=healthy",),
            ("Check broker ISR metrics",),
        ),
    ],
    "flink_job_failure": [
        Pattern(
            "schema_mismatch",
            "Incompatible schema change on risk-events (writer v7 vs reader v6)",
            "The producer published schema v7 changing `amount` from decimal to string; the Flink job's v6 reader "
            "cannot deserialize the records and the job restarts until it fails.",
            ("schemamismatchexception", "incompatible", "writer schema v7", "reader schema v6",
             "compatible=false", "deserialization"),
            ("compatible=true",),
            ("Confirm which producers publish v7", "Confirm checkpoint chk-18842 is restorable"),
        ),
        Pattern(
            "checkpoint_failure",
            "Checkpoint timeouts",
            "Checkpoints expire before completion, causing job restarts.",
            ("checkpoint expired", "checkpoint timeout"),
            ("last checkpoint completed",),
            ("Review checkpoint duration trend",),
        ),
        Pattern(
            "taskmanager_resources",
            "TaskManager resource exhaustion",
            "TaskManagers are lost due to memory pressure.",
            ("taskmanager lost", "container killed"),
            (),
            ("Review TaskManager memory",),
        ),
    ],
    "payment_processing_delay": [
        Pattern(
            "downstream_dependency_outage",
            "fraud-scoring-service (synthetic vendor) outage",
            "Payment authorizations wait on the fraud-scoring dependency, which is down; payments queue in "
            "store-and-forward.",
            ("fraud-scoring-service is down", "fraud score timeout", "vendor endpoint unreachable",
             "store-and-forward", "circuit breaker open"),
            ("fraud-scoring-service is healthy",),
            ("Confirm store-and-forward depth vs SLA", "Confirm vendor status page (synthetic)"),
        ),
        Pattern(
            "router_saturation",
            "payment-router thread-pool saturation",
            "Router worker threads are saturated.",
            ("thread pool exhausted", "router saturation"),
            ("router threads normal",),
            ("Check router thread metrics",),
        ),
    ],
    "mq_queue_backlog": [
        Pattern(
            "consumer_unavailable",
            "MQ settlement consumer unavailable (channel stopped)",
            "The consumer's channel stopped after MQRC_CONNECTION_BROKEN; with no open input handles the queue "
            "depth grows toward its maximum.",
            ("open_input_count=0", "mqrc_connection_broken", "channel_state=stopped", "mq-settlement-consumer is down",
             "queue depth approaching max"),
            ("open_input_count=1",),
            ("Confirm no poison messages at queue head", "Review DLQ contents before any replay"),
        ),
        Pattern(
            "slow_ledger_commits",
            "Slow core-ledger commits",
            "Consumer is connected but ledger commits are slow.",
            ("slow commit", "ledger latency high"),
            ("core-ledger is healthy",),
            ("Check core-ledger commit latency",),
        ),
    ],
    "snowflake_ingestion_delay": [
        Pattern(
            "pipeline_task_suspended",
            "Ingestion task suspended after warehouse outage",
            "The load task was auto-suspended after a transient warehouse outage and has not resumed; data "
            "freshness lag exceeds the SLA.",
            ("task_state=suspended", "auto-suspended", "warehouse unavailable", "freshness_lag_minutes=185"),
            ("task_state=started",),
            ("Confirm warehouse is available", "Check failed load files"),
        ),
        Pattern(
            "file_format_change",
            "Upstream file format change",
            "Load files fail to parse after an upstream format change.",
            ("parse failure", "column count mismatch", "file format changed"),
            ("no parse errors",),
            ("Inspect a failed staged file",),
        ),
    ],
    "duplicate_events": [
        Pattern(
            "producer_retry_storm",
            "Producer retry storm without idempotency keys",
            "The payments-event-publisher retried timed-out sends without idempotency keys, emitting duplicates.",
            ("idempotency key missing", "retrying send", "duplicate_ratio=0.043", "payments-event-publisher",
             "producer retries"),
            ("idempotence enabled",),
            ("Confirm producer idempotence setting", "Reconcile duplicates against the synthetic ledger"),
        ),
        Pattern(
            "consumer_offset_reset",
            "Consumer offset reset / rebalance replay",
            "A consumer reset offsets and re-read events.",
            ("offset reset detected", "rebalance storm"),
            ("no offset resets",),
            ("Review consumer offset history",),
        ),
    ],
    "data_quality_failure": [
        Pattern(
            "upstream_data_defect",
            "Upstream extract contains null counterparty IDs",
            "The upstream positions extract delivered rows with null counterparty_id, failing mandatory checks.",
            ("counterparty_id_not_null", "failed_rows=312", "null counterparty", "upstream extract"),
            ("all checks passing",),
            ("Request corrected extract from upstream owner", "Confirm no downstream report used the batch"),
        ),
        Pattern(
            "rule_misconfiguration",
            "Validation rule misconfiguration",
            "A recently changed rule rejects valid data.",
            ("rule changed", "threshold misconfigured"),
            ("rules unchanged",),
            ("Diff DQ suite configuration",),
        ),
    ],
    "fraud_alert": [
        Pattern(
            "refund_retry_defect",
            "Refund-service retry defect creating duplicate refunds",
            "Duplicate refund requests originate from refund-service retries after ledger timeouts.",
            ("duplicate refund", "refund-service", "ledger timeout", "retrying refund"),
            (),
            ("Freeze automated refunds via fraud-ops procedure (manual)", "Reconcile refunds (synthetic)"),
        ),
    ],
}


def _batch(obs: dict[str, Any], key: str = "batch_id") -> str | None:
    return (obs.get("incident_attributes") or {}).get(key)


def _plan_renderer(inc: dict[str, Any], obs: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    attrs = obs.get("incident_attributes") or {}
    return {
        "summary": "Restore document-renderer with a rolling restart, then re-queue the failed statement batch once "
        "the renderer is healthy.",
        "actions": [
            {
                "step": 1,
                "tool_name": "simulate_restart_document_renderer",
                "target_resource": "document-renderer",
                "parameters": {"service_key": "document-renderer", "strategy": "rolling",
                               "reason": "Heap exhaustion; 0/3 instances ready"},
                "rationale": "document-renderer is DOWN with OutOfMemoryError and exhausted connection pool; the "
                "runbook prescribes a rolling restart after capturing diagnostics.",
                "expected_effect": "Renderer instances return to ready and render 5xx rate falls to zero.",
                "risks": "Brief additional unavailability; heap exhaustion may recur if a leak exists.",
                "prerequisites": ["template-store healthy", "Manager approval (medium risk)"],
                "rollback_option": "Not reversible; escalate to platform on-call if the restart does not recover.",
                "depends_on_step": None,
                "evidence_refs": refs[:4],
            },
            {
                "step": 2,
                "tool_name": "simulate_reprocess_failed_statement",
                "target_resource": "statement-generator",
                "parameters": {"service_key": "statement-generator", "batch_id": attrs.get("batch_id", "unknown"),
                               "max_documents": int(attrs.get("batch_documents", 12400))},
                "rationale": "The failed batch must be re-queued after the renderer recovers; reprocessing is "
                "idempotent per batch.",
                "expected_effect": "Failed statements are regenerated and the batch completes.",
                "risks": "Load spike on the renderer; bounded by max_documents.",
                "prerequisites": ["Step 1 succeeded and document-renderer healthy"],
                "rollback_option": "Simulated rollback restores the batch's previous state.",
                "depends_on_step": 1,
                "evidence_refs": refs[:3],
            },
        ],
        "manual_steps": ["Capture a heap dump from one renderer instance before restart (synthetic)",
                         "Open a problem record to investigate the suspected memory leak"],
        "not_recommended": [{"tool_name": "simulate_replay_dead_letter_events",
                             "reason": "No dead-letter backlog is involved; replay would add duplicate risk."}],
        "evidence_refs": refs[:5],
    }


def _plan_template(inc: dict[str, Any], obs: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    attrs = obs.get("incident_attributes") or {}
    return {
        "summary": "Restore the missing template from its last approved version, then reprocess the failed batch.",
        "actions": [
            {
                "step": 1,
                "tool_name": "simulate_restore_missing_template",
                "target_resource": "template-store",
                "parameters": {"template_id": attrs.get("template_id", "unknown"),
                               "restore_from_version": attrs.get("template_restore_version", "v2")},
                "rationale": "Template validation reports the template missing; the runbook restores the last "
                "approved version rather than publishing a new one.",
                "expected_effect": "Template validates as active; rendering can resume.",
                "risks": "Restoring an outdated layout; mitigated by using the last approved version.",
                "prerequisites": ["Manager approval (medium risk)"],
                "rollback_option": "Simulated rollback removes the restored version.",
                "depends_on_step": None,
                "evidence_refs": refs[:4],
            },
            {
                "step": 2,
                "tool_name": "simulate_reprocess_failed_statement",
                "target_resource": "investment-statement-generator",
                "parameters": {"service_key": "investment-statement-generator",
                               "batch_id": attrs.get("batch_id", "unknown"),
                               "max_documents": int(attrs.get("batch_documents", 3100))},
                "rationale": "Re-queue the failed batch once the template is available.",
                "expected_effect": "Batch completes.",
                "risks": "None beyond normal rendering load.",
                "prerequisites": ["Step 1 succeeded"],
                "rollback_option": "Simulated rollback restores the batch's previous state.",
                "depends_on_step": 1,
                "evidence_refs": refs[:3],
            },
        ],
        "manual_steps": ["Investigate why the template publication job removed the active version"],
        "not_recommended": [],
        "evidence_refs": refs[:5],
    }


def _plan_kafka(inc: dict[str, Any], obs: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    return {
        "summary": "Scale the consumer group within bounds to restore throughput; replay of dead-letter events is "
        "optional, high risk and only after lag recovers, with explicit approval.",
        "actions": [
            {
                "step": 1,
                "tool_name": "simulate_scale_consumer_group",
                "target_resource": "transaction-enricher",
                "parameters": {"consumer_group": "cg-transaction-enricher", "target_replicas": 6},
                "rationale": "Throughput is below the ingest rate with evenly distributed lag; adding consumers "
                "(12 partitions available) restores headroom while the lookup latency is investigated.",
                "expected_effect": "Throughput exceeds ingest; lag drains.",
                "risks": "Higher load on customer-profile-cache; bounded to 6 replicas.",
                "prerequisites": ["Manager approval (medium risk)", "Partitions >= target replicas"],
                "rollback_option": "Simulated rollback restores the previous replica count.",
                "depends_on_step": None,
                "evidence_refs": refs[:4],
            },
            {
                "step": 2,
                "tool_name": "simulate_replay_dead_letter_events",
                "target_resource": "transaction-enricher",
                "parameters": {"source": "card-transactions.dlq", "max_events": 214, "idempotency_check": True},
                "rationale": "214 events timed out into the DLQ; replay only after lag recovers and with idempotent "
                "processing confirmed.",
                "expected_effect": "Dead-lettered transactions are enriched.",
                "risks": "Duplicate processing if idempotency is not guaranteed; replay cannot be undone.",
                "prerequisites": ["Step 1 succeeded", "Lag below threshold", "Independent manager approval"],
                "rollback_option": "Not reversible; compensation would be manual.",
                "depends_on_step": 1,
                "evidence_refs": refs[:3],
            },
        ],
        "manual_steps": ["Investigate customer-profile-cache latency (synthetic)",
                         "Confirm consumer idempotency before approving any replay"],
        "not_recommended": [{"tool_name": "purge_kafka_topic", "reason": "Destructive and prohibited."}],
        "evidence_refs": refs[:5],
    }


def _plan_flink(inc: dict[str, Any], obs: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    return {
        "summary": "Restart the Flink job from its last checkpoint with the consumer pinned to the last compatible "
        "reader schema (v6). The production schema registry is not modified; the producer fix goes through change "
        "management.",
        "actions": [
            {
                "step": 1,
                "tool_name": "simulate_restart_flink_job_from_checkpoint",
                "target_resource": "flink-risk-aggregator",
                "parameters": {"job_name": "flink-risk-aggregator", "checkpoint": "latest",
                               "pin_reader_schema_version": 6},
                "rationale": "Compatibility check shows v7 is incompatible with reader v6; pinning the reader and "
                "restoring from checkpoint resumes processing of compatible events without touching the registry.",
                "expected_effect": "Job RUNNING; incompatible v7 events routed to quarantine for later reprocessing.",
                "risks": "Events in v7 format are quarantined until the producer is fixed.",
                "prerequisites": ["Independent manager approval (high risk)", "Checkpoint chk-18842 restorable"],
                "rollback_option": "Simulated rollback restores the previous job configuration snapshot.",
                "depends_on_step": None,
                "evidence_refs": refs[:4],
            }
        ],
        "manual_steps": ["Raise a change request for the producer to publish a backward-compatible schema (v8)",
                         "Reprocess quarantined v7 events after the producer fix"],
        "not_recommended": [
            {"tool_name": "modify_production_schema", "reason": "Prohibited: production schema changes need CAB."},
            {"tool_name": "change_schema_registry_compatibility", "reason": "Prohibited: would hide the break."},
        ],
        "evidence_refs": refs[:5],
    }


def _plan_payments(inc: dict[str, Any], obs: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    return {
        "summary": "No automated remediation is appropriate: the failing dependency is an external (synthetic) "
        "vendor and payment flows are excluded from automated action. Escalate and monitor store-and-forward.",
        "actions": [],
        "manual_steps": ["Engage the fraud-scoring vendor escalation path (synthetic contact)",
                         "Confirm store-and-forward depth stays within SLA",
                         "Do not bypass fraud scoring"],
        "not_recommended": [{"tool_name": "execute_payment",
                             "reason": "Prohibited: AI tooling never executes or replays payments."}],
        "evidence_refs": refs[:5],
    }


def _plan_mq(inc: dict[str, Any], obs: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    return {
        "summary": "Restart the MQ settlement consumer channel so the backlog drains; review the DLQ separately.",
        "actions": [
            {
                "step": 1,
                "tool_name": "simulate_restart_mq_consumer",
                "target_resource": "mq-settlement-consumer",
                "parameters": {"consumer": "mq-settlement-consumer", "channel": "SETTLEMENT.SVRCONN"},
                "rationale": "open_input_count is 0 and the channel is STOPPED after MQRC_CONNECTION_BROKEN; the "
                "runbook restarts the consumer channel.",
                "expected_effect": "Consumer reconnects; queue depth drains below threshold.",
                "risks": "Burst load on core-ledger during drain.",
                "prerequisites": ["Manager approval (medium risk)", "No poison message at queue head"],
                "rollback_option": "Not reversible; verification decides the outcome.",
                "depends_on_step": None,
                "evidence_refs": refs[:4],
            }
        ],
        "manual_steps": ["Review PAYMENT.SETTLEMENT.DLQ (37 messages) - replay only with explicit high-risk approval"],
        "not_recommended": [{"tool_name": "delete_queue_messages", "reason": "Destructive and prohibited."}],
        "evidence_refs": refs[:5],
    }


def _plan_snowflake(inc: dict[str, Any], obs: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    return {
        "summary": "Resume and re-run the suspended ingestion task; loads are de-duplicated by load key.",
        "actions": [
            {
                "step": 1,
                "tool_name": "simulate_rerun_snowflake_pipeline",
                "target_resource": "snowflake-ingestion",
                "parameters": {"pipeline": "snowpipe-card-settlements", "task": "LOAD_CARD_SETTLEMENTS"},
                "rationale": "Task is SUSPENDED after a transient warehouse outage; re-running is idempotent.",
                "expected_effect": "Task STARTED; freshness lag returns under 30 minutes.",
                "risks": "Warehouse credit consumption (synthetic).",
                "prerequisites": ["Warehouse available"],
                "rollback_option": "Not supported; loads are de-duplicated by load key.",
                "depends_on_step": None,
                "evidence_refs": refs[:4],
            }
        ],
        "manual_steps": ["Review the warehouse outage record (synthetic)"],
        "not_recommended": [],
        "evidence_refs": refs[:5],
    }


def _plan_duplicates(inc: dict[str, Any], obs: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    return {
        "summary": "No automated mutation: duplicates are quarantined by event-dedup-service. Fix producer "
        "idempotence through change management and reconcile.",
        "actions": [],
        "manual_steps": ["Enable producer idempotence via change request", "Reconcile quarantined duplicates",
                         "Never delete events; keep the audit trail"],
        "not_recommended": [
            {"tool_name": "delete_queue_messages", "reason": "Prohibited destructive action."},
            {"tool_name": "purge_kafka_topic", "reason": "Prohibited destructive action."},
        ],
        "evidence_refs": refs[:5],
    }


def _plan_dq(inc: dict[str, Any], obs: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    return {
        "summary": "Data must be corrected upstream; re-running validations confirms the current state but will not "
        "resolve the incident until a corrected extract arrives. Checks are never bypassed.",
        "actions": [
            {
                "step": 1,
                "tool_name": "simulate_rerun_data_quality_checks",
                "target_resource": "reporting-dq-validator",
                "parameters": {"suite": "regulatory-daily-positions"},
                "rationale": "Confirms whether the failure persists (read-only effect on data).",
                "expected_effect": "Updated validation results.",
                "risks": "None; validations do not modify data.",
                "prerequisites": [],
                "rollback_option": "Not applicable.",
                "depends_on_step": None,
                "evidence_refs": refs[:3],
            }
        ],
        "manual_steps": ["Request a corrected extract from the upstream owner (synthetic)",
                         "Hold the regulatory report until checks pass"],
        "not_recommended": [{"tool_name": "bypass_data_quality_checks", "reason": "Prohibited control bypass."}],
        "evidence_refs": refs[:5],
    }


def _plan_fraud(inc: dict[str, Any], obs: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    return {
        "summary": "Restricted fraud-operations incident: no automated actions. Follow the restricted escalation "
        "procedure.",
        "actions": [],
        "manual_steps": ["Escalate to fraud operations per the restricted procedure",
                         "Freeze automated refunds (manual, fraud-ops authority)"],
        "not_recommended": [{"tool_name": "modify_account_balance", "reason": "Prohibited."}],
        "evidence_refs": refs[:5],
    }


PLAN_BUILDERS: dict[str, Callable[[dict[str, Any], dict[str, Any], list[str]], dict[str, Any]]] = {
    "renderer_outage": _plan_renderer,
    "missing_template": _plan_template,
    "consumer_processing_bottleneck": _plan_kafka,
    "schema_mismatch": _plan_flink,
    "downstream_dependency_outage": _plan_payments,
    "consumer_unavailable": _plan_mq,
    "pipeline_task_suspended": _plan_snowflake,
    "producer_retry_storm": _plan_duplicates,
    "upstream_data_defect": _plan_dq,
    "refund_retry_defect": _plan_fraud,
}
