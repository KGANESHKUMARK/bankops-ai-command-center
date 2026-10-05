"""Guided demo scenarios (all synthetic)."""

from __future__ import annotations

SCENARIOS = [
    {
        "key": "statement_outage",
        "title": "A. Statement generation outage",
        "incident_number": "INC-1001",
        "summary": "Nightly retail statements fail because the downstream document-renderer is down (heap exhaustion).",
        "personas": {"investigator": "ops.analyst", "approver": "ops.manager"},
        "steps": [
            "Sign in as ops.analyst and start the scenario (starts a bounded AI investigation).",
            "Watch the live timeline: triage, authorized retrieval, diagnosis, planning, advisory review, policy gate.",
            "Review evidence citations and ranked hypotheses (renderer outage should rank first).",
            "The policy engine requires manager approval for the medium-risk renderer restart; the low-risk batch "
            "reprocess is allowed but depends on step 1.",
            "Sign in as ops.manager, open the Approval Center and approve with explicit confirmation.",
            "The workflow resumes: simulated restart, reprocess, verification and final report.",
            "Inspect the audit trail and verify the hash chain in the Governance Center.",
        ],
        "expected_outcome": "Incident verified resolved after two simulated actions; full audit trail recorded.",
    },
    {
        "key": "kafka_lag",
        "title": "B. Kafka consumer lag",
        "incident_number": "INC-1002",
        "summary": "Consumer lag grows because slow enrichment lookups cut consumer throughput below the ingest rate.",
        "personas": {"investigator": "ops.analyst", "approver": "ops.manager"},
        "steps": [
            "Start the scenario and review synthetic stream metrics (throughput below ingest, evenly distributed lag).",
            "The plan scales the consumer group (medium risk) and proposes a DLQ replay as a separate high-risk step.",
            "As ops.manager approve the scale-out but reject the replay (e.g. RISK_TOO_HIGH) until idempotency is "
            "confirmed - replay never happens without explicit approval.",
            "Verification checks consumer lag against the threshold.",
        ],
        "expected_outcome": "Lag recovers after the approved scale-out; the rejected replay is recorded, never executed.",
    },
    {
        "key": "schema_mismatch",
        "title": "C. Streaming schema mismatch",
        "incident_number": "INC-1003",
        "summary": "A producer registered an incompatible schema (v7) and the Flink job (reader v6) fails.",
        "personas": {"investigator": "ops.analyst", "approver": "ops.manager"},
        "steps": [
            "Start the scenario; the schema compatibility runbook and a compatibility check are cited.",
            "The plan restarts the job from checkpoint with the reader pinned to v6 (high risk) and lists production "
            "schema changes as prohibited alternatives (denied by policy P-002).",
            "High risk requires an operations manager who is not the requester to approve.",
            "Verification confirms the job is RUNNING; the producer fix is routed to change management.",
        ],
        "expected_outcome": "Job restored without silently changing production schemas.",
    },
]
