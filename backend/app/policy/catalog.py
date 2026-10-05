"""Action risk catalog: the authoritative risk classification for every tool.

The LLM may *propose* any tool name; only names present here (and implemented in
the tool registry) can ever run, and prohibited names can never run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain import RiskLevel, Role


@dataclass(frozen=True)
class ActionPolicy:
    tool_name: str
    risk: RiskLevel
    description: str
    allowed_targets: tuple[str, ...] = ()
    rollback_supported: bool = False
    rollback_note: str = ""
    approver_roles: tuple[Role, ...] = field(default_factory=tuple)


_MED_APPROVERS = (Role.OPERATIONS_MANAGER, Role.DEMO_ADMIN)
_HIGH_APPROVERS = (Role.OPERATIONS_MANAGER,)

ACTION_CATALOG: dict[str, ActionPolicy] = {
    p.tool_name: p
    for p in [
        # ---- read-only diagnostics ------------------------------------------------
        ActionPolicy("get_incident_details", RiskLevel.READ_ONLY, "Read incident facts and timeline."),
        ActionPolicy("get_service_health", RiskLevel.READ_ONLY, "Read synthetic service health/metrics."),
        ActionPolicy("get_service_dependencies", RiskLevel.READ_ONLY, "Read the synthetic dependency map."),
        ActionPolicy("get_recent_synthetic_logs", RiskLevel.READ_ONLY, "Read recent synthetic log lines."),
        ActionPolicy("search_authorized_runbooks", RiskLevel.READ_ONLY, "Authorized RAG search over runbooks."),
        ActionPolicy("search_incident_history", RiskLevel.READ_ONLY, "Find similar authorized past incidents."),
        ActionPolicy("inspect_synthetic_queue_metrics", RiskLevel.READ_ONLY, "Read synthetic MQ queue metrics."),
        ActionPolicy("inspect_synthetic_stream_metrics", RiskLevel.READ_ONLY, "Read synthetic Kafka/Flink metrics."),
        ActionPolicy("validate_synthetic_document_template", RiskLevel.READ_ONLY, "Validate a synthetic template."),
        ActionPolicy(
            "validate_synthetic_schema_compatibility", RiskLevel.READ_ONLY, "Check synthetic schema compatibility."
        ),
        ActionPolicy("verify_service_health", RiskLevel.READ_ONLY, "Post-action health verification."),
        ActionPolicy("verify_incident_resolution", RiskLevel.READ_ONLY, "Evaluate incident resolution criteria."),
        # ---- low risk -----------------------------------------------------------------
        ActionPolicy(
            "simulate_reprocess_failed_statement",
            RiskLevel.LOW,
            "Re-queue a failed synthetic statement batch for rendering (idempotent per batch).",
            allowed_targets=("statement-generator", "investment-statement-generator"),
            rollback_supported=True,
            rollback_note="Simulated rollback restores the batch to its previous failed state.",
            approver_roles=_MED_APPROVERS,
        ),
        ActionPolicy(
            "simulate_rerun_snowflake_pipeline",
            RiskLevel.LOW,
            "Re-run the failed synthetic ingestion task (loads are de-duplicated by load key).",
            allowed_targets=("snowflake-ingestion",),
            rollback_supported=False,
            rollback_note="Not supported: an idempotent re-load has no meaningful inverse; loads are de-duplicated.",
            approver_roles=_MED_APPROVERS,
        ),
        ActionPolicy(
            "simulate_rerun_data_quality_checks",
            RiskLevel.LOW,
            "Re-run synthetic data-quality validations (never bypasses failed checks).",
            allowed_targets=("reporting-dq-validator",),
            rollback_supported=False,
            rollback_note="Not applicable: re-running validations does not change data.",
            approver_roles=_MED_APPROVERS,
        ),
        # ---- medium risk --------------------------------------------------------------
        ActionPolicy(
            "simulate_restart_document_renderer",
            RiskLevel.MEDIUM,
            "Rolling restart of the synthetic document-renderer service.",
            allowed_targets=("document-renderer",),
            rollback_supported=False,
            rollback_note="Not supported: a restart cannot be undone; post-action verification decides the outcome.",
            approver_roles=_MED_APPROVERS,
        ),
        ActionPolicy(
            "simulate_restore_missing_template",
            RiskLevel.MEDIUM,
            "Restore a missing synthetic statement template from the last approved version.",
            allowed_targets=("template-store",),
            rollback_supported=True,
            rollback_note="Simulated rollback removes the restored template version.",
            approver_roles=_MED_APPROVERS,
        ),
        ActionPolicy(
            "simulate_restart_mq_consumer",
            RiskLevel.MEDIUM,
            "Restart the synthetic MQ settlement consumer channel.",
            allowed_targets=("mq-settlement-consumer",),
            rollback_supported=False,
            rollback_note="Not supported: a restart cannot be undone; verification decides the outcome.",
            approver_roles=_MED_APPROVERS,
        ),
        ActionPolicy(
            "simulate_scale_consumer_group",
            RiskLevel.MEDIUM,
            "Scale the synthetic Kafka consumer group within a bounded replica range.",
            allowed_targets=("transaction-enricher",),
            rollback_supported=True,
            rollback_note="Simulated rollback restores the previous replica count.",
            approver_roles=_MED_APPROVERS,
        ),
        # ---- high risk ------------------------------------------------------------------
        ActionPolicy(
            "simulate_replay_dead_letter_events",
            RiskLevel.HIGH,
            "Replay a bounded number of synthetic dead-letter events (risk of duplicate processing).",
            allowed_targets=("transaction-enricher", "mq-settlement-consumer"),
            rollback_supported=False,
            rollback_note="Not supported: replayed events cannot be un-sent; compensation is a manual process.",
            approver_roles=_HIGH_APPROVERS,
        ),
        ActionPolicy(
            "simulate_restart_flink_job_from_checkpoint",
            RiskLevel.HIGH,
            "Restart the synthetic Flink job from its last checkpoint with the consumer pinned to the last "
            "compatible schema version (does not modify the production schema registry).",
            allowed_targets=("flink-risk-aggregator",),
            rollback_supported=True,
            rollback_note="Simulated rollback restores the previous job configuration snapshot.",
            approver_roles=_HIGH_APPROVERS,
        ),
    ]
}

# Never executable, regardless of role, approval, configuration or model output.
PROHIBITED_ACTIONS: dict[str, str] = {
    "execute_payment": "Initiating payments is out of scope for operations tooling.",
    "transfer_funds": "Moving funds is never permitted from an AI workflow.",
    "modify_account_balance": "Customer account modification is prohibited.",
    "delete_customer_record": "Destructive customer data operations are prohibited.",
    "bulk_export_customer_data": "Bulk data export is a data-exfiltration risk.",
    "modify_production_schema": "Production schema changes require change-advisory approval outside this tool.",
    "change_schema_registry_compatibility": "Schema registry settings must not be changed silently.",
    "disable_audit_logging": "Audit logging can never be disabled.",
    "purge_kafka_topic": "Destructive stream operations are prohibited.",
    "delete_queue_messages": "Destructive queue operations are prohibited.",
    "bypass_data_quality_checks": "Data quality controls must not be bypassed.",
    "drop_database_table": "Destructive database operations are prohibited.",
    "execute_sql": "Arbitrary SQL execution is prohibited.",
    "run_shell_command": "Shell execution is prohibited.",
    "fetch_url": "Arbitrary network fetches are prohibited (SSRF risk).",
    "execute_python": "Arbitrary code execution is prohibited.",
}


def risk_of(tool_name: str) -> RiskLevel:
    if tool_name in PROHIBITED_ACTIONS:
        return RiskLevel.PROHIBITED
    policy = ACTION_CATALOG.get(tool_name)
    return policy.risk if policy else RiskLevel.PROHIBITED
