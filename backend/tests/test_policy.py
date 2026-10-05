"""Deterministic policy engine: risk decisions, approvals, separation of duties, execution re-checks.

These tests use no database and no model: the policy engine must work when the LLM is unavailable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.policy.catalog import ACTION_CATALOG, PROHIBITED_ACTIONS
from app.policy.engine import Actor, PolicyEngine, compute_action_hash

T = "contoso-demo"
ANALYST = Actor("u-analyst", "ops.analyst", "operations_analyst", T)
MANAGER = Actor("u-manager", "ops.manager", "operations_manager", T)
MANAGER2 = Actor("u-manager2", "ops.manager2", "operations_manager", T)
ADMIN = Actor("u-admin", "demo.admin", "demo_admin", T)
AUDITOR = Actor("u-auditor", "risk.auditor", "auditor", T)
VIEWER = Actor("u-viewer", "readonly.viewer", "read_only", T)
OTHER_TENANT = Actor("u-fab", "fab.manager", "operations_manager", "fabrikam-demo")


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine(Settings(_env_file=None))


def evaluate(engine: PolicyEngine, actor: Actor, tool: str, target: str | None = None, status: str = "open",
             tenant: str = T, classification: str = "internal"):  # type: ignore[no-untyped-def]
    return engine.evaluate_action(actor, tool_name=tool, target_resource=target, incident_tenant_id=tenant,
                                  incident_status=status, incident_classification=classification)


def make_action(requested_by: str = ANALYST.user_id, risk: str = "high", tool: str = "simulate_restart_flink_job_from_checkpoint",
                target: str = "flink-risk-aggregator", status: str = "pending_approval", requires_approval: bool = True):
    params = {"job_name": "flink-risk-aggregator", "checkpoint": "latest", "pin_reader_schema_version": 6}
    action = SimpleNamespace(tenant_id=T, tool_name=tool, target_resource=target, parameters=params, incident_id="inc-1",
                             investigation_id="run-1", plan_version=1, step_index=1, risk_level=risk, status=status,
                             requested_by=requested_by, requires_approval=requires_approval)
    action.action_hash = compute_action_hash(tool_name=tool, target_resource=target, parameters=params, incident_id="inc-1",
                                             investigation_id="run-1", plan_version=1, step_index=1)
    return action


def make_approval(action, *, risk: str = "high", roles=("operations_manager",), status: str = "pending",
                  expires_in: int = 30, tenant: str = T):  # type: ignore[no-untyped-def]
    return SimpleNamespace(tenant_id=tenant, risk_level=risk, required_roles=list(roles), status=status,
                           expires_at=datetime.now(UTC) + timedelta(minutes=expires_in), requested_by=action.requested_by,
                           action_hash=action.action_hash, incident_id=action.incident_id, target_resource=action.target_resource,
                           decided_by=None)


# ------------------------------------------------------------------ risk classes
def test_read_only_diagnostics_allowed_for_authorized_roles(engine: PolicyEngine) -> None:
    for actor in (ANALYST, MANAGER, ADMIN):
        d = evaluate(engine, actor, "get_service_health")
        assert d.decision == "allow" and d.rule_ids == ["P-006"], actor.role


def test_auditor_and_read_only_cannot_run_diagnostics(engine: PolicyEngine) -> None:
    for actor in (AUDITOR, VIEWER):
        d = evaluate(engine, actor, "get_service_health")
        assert d.decision == "deny" and d.rule_ids == ["P-003"], actor.role


@pytest.mark.parametrize("tool", sorted(PROHIBITED_ACTIONS))
def test_prohibited_actions_never_allowed_even_for_admin(engine: PolicyEngine, tool: str) -> None:
    for actor in (ADMIN, MANAGER, ANALYST):
        d = evaluate(engine, actor, tool, target="core-ledger")
        assert d.decision == "deny" and d.rule_ids == ["P-002"] and d.risk_level == "prohibited"


def test_unknown_tool_denied(engine: PolicyEngine) -> None:
    d = evaluate(engine, ADMIN, "approve_all_pending_actions")
    assert d.decision == "deny" and d.rule_ids == ["P-001"]


def test_low_risk_allowed_without_approval_by_default(engine: PolicyEngine) -> None:
    d = evaluate(engine, ANALYST, "simulate_reprocess_failed_statement", target="statement-generator")
    assert d.decision == "allow" and d.risk_level == "low"


def test_low_risk_requires_approval_when_configured() -> None:
    eng = PolicyEngine(Settings(_env_file=None, low_risk_requires_approval=True))
    d = evaluate(eng, ANALYST, "simulate_reprocess_failed_statement", target="statement-generator")
    assert d.decision == "require_approval"


def test_medium_risk_requires_manager_or_admin_approval(engine: PolicyEngine) -> None:
    d = evaluate(engine, ANALYST, "simulate_restart_document_renderer", target="document-renderer")
    assert d.decision == "require_approval" and set(d.required_approver_roles) == {"operations_manager", "demo_admin"}


def test_medium_risk_configurable() -> None:
    eng = PolicyEngine(Settings(_env_file=None, medium_risk_requires_approval=False))
    assert evaluate(eng, ANALYST, "simulate_restart_document_renderer", target="document-renderer").decision == "allow"


def test_high_risk_always_requires_manager_approval() -> None:
    eng = PolicyEngine(Settings(_env_file=None, medium_risk_requires_approval=False, low_risk_requires_approval=False))
    d = evaluate(eng, ADMIN, "simulate_replay_dead_letter_events", target="transaction-enricher")
    assert d.decision == "require_approval" and d.required_approver_roles == ["operations_manager"]


def test_target_outside_allowlist_denied(engine: PolicyEngine) -> None:
    d = evaluate(engine, ANALYST, "simulate_restart_document_renderer", target="core-ledger")
    assert d.decision == "deny" and d.rule_ids == ["P-005"]


def test_no_mutations_on_closed_incident(engine: PolicyEngine) -> None:
    d = evaluate(engine, ANALYST, "simulate_restart_document_renderer", target="document-renderer", status="closed")
    assert d.decision == "deny" and d.rule_ids == ["P-010"]


def test_tenant_mismatch_denied(engine: PolicyEngine) -> None:
    d = evaluate(engine, OTHER_TENANT, "simulate_restart_document_renderer", target="document-renderer")
    assert d.decision == "deny" and d.rule_ids == ["P-004"]


def test_classification_clearance_enforced(engine: PolicyEngine) -> None:
    d = evaluate(engine, ANALYST, "get_service_health", classification="restricted")
    assert d.decision == "deny" and d.rule_ids == ["P-011"]


def test_roles_without_request_permission_cannot_request_actions(engine: PolicyEngine) -> None:
    for actor in (AUDITOR, VIEWER):
        d = evaluate(engine, actor, "simulate_restart_document_renderer", target="document-renderer")
        assert d.decision == "deny" and d.rule_ids == ["P-003"]


def test_every_catalog_mutating_tool_has_targets_and_approvers() -> None:
    for policy in ACTION_CATALOG.values():
        if policy.risk.value in ("low", "medium", "high"):
            assert policy.allowed_targets and policy.approver_roles and policy.rollback_note


# --------------------------------------------------------------------- approvals
def test_requester_cannot_approve_own_high_risk_action(engine: PolicyEngine) -> None:
    action = make_action(requested_by=MANAGER.user_id)
    d = engine.evaluate_approval(MANAGER, approval=make_approval(action), action=action, decision="approve")
    assert d.decision == "deny" and d.rule_ids == ["A-005"]


def test_independent_manager_can_approve_high_risk(engine: PolicyEngine) -> None:
    action = make_action(requested_by=MANAGER.user_id)
    d = engine.evaluate_approval(MANAGER2, approval=make_approval(action), action=action, decision="approve")
    assert d.decision == "allow"


def test_admin_cannot_approve_high_risk(engine: PolicyEngine) -> None:
    action = make_action()
    d = engine.evaluate_approval(ADMIN, approval=make_approval(action), action=action, decision="approve")
    assert d.decision == "deny" and d.rule_ids == ["A-002"]


def test_self_approval_of_medium_disabled_by_default_and_configurable() -> None:
    action = make_action(requested_by=MANAGER.user_id, risk="medium")
    approval = make_approval(action, risk="medium", roles=("operations_manager", "demo_admin"))
    default = PolicyEngine(Settings(_env_file=None))
    assert default.evaluate_approval(MANAGER, approval=approval, action=action, decision="approve").rule_ids == ["A-005"]
    relaxed = PolicyEngine(Settings(_env_file=None, allow_self_approval_medium=True))
    assert relaxed.evaluate_approval(MANAGER, approval=approval, action=action, decision="approve").decision == "allow"


def test_non_approver_roles_rejected(engine: PolicyEngine) -> None:
    action = make_action()
    for actor in (ANALYST, AUDITOR, VIEWER):
        d = engine.evaluate_approval(actor, approval=make_approval(action), action=action, decision="approve")
        assert d.decision == "deny" and d.rule_ids == ["A-001"]


def test_expired_approval_rejected(engine: PolicyEngine) -> None:
    action = make_action()
    d = engine.evaluate_approval(MANAGER, approval=make_approval(action, expires_in=-1), action=action, decision="approve")
    assert d.rule_ids == ["A-004"]


def test_duplicate_or_stale_decisions_rejected(engine: PolicyEngine) -> None:
    action = make_action()
    for status in ("approved", "rejected", "cancelled", "expired", "invalidated"):
        d = engine.evaluate_approval(MANAGER, approval=make_approval(action, status=status), action=action, decision="approve")
        assert d.rule_ids == ["A-003"]


def test_changed_plan_invalidates_approval(engine: PolicyEngine) -> None:
    action = make_action()
    approval = make_approval(action)
    action.parameters = {**action.parameters, "pin_reader_schema_version": 7}
    d = engine.evaluate_approval(MANAGER, approval=approval, action=action, decision="approve")
    assert d.decision == "deny" and d.rule_ids == ["A-006"]


def test_cross_tenant_approval_rejected(engine: PolicyEngine) -> None:
    action = make_action()
    d = engine.evaluate_approval(OTHER_TENANT, approval=make_approval(action), action=action, decision="approve")
    assert d.rule_ids == ["A-007"]


def test_action_must_be_pending(engine: PolicyEngine) -> None:
    action = make_action(status="approved")
    d = engine.evaluate_approval(MANAGER, approval=make_approval(action), action=action, decision="approve")
    assert d.rule_ids == ["A-008"]


# --------------------------------------------------------------------- execution
def test_execution_requires_valid_approval(engine: PolicyEngine) -> None:
    action = make_action(status="approved")
    assert engine.evaluate_execution(action=action, approval=None).decision == "deny"
    approval = make_approval(action, status="approved")
    approval.decided_by = MANAGER2.user_id
    assert engine.evaluate_execution(action=action, approval=approval).decision == "allow"


def test_execution_refuses_self_approved_high_risk_and_tampering(engine: PolicyEngine) -> None:
    action = make_action(status="approved", requested_by=MANAGER.user_id)
    approval = make_approval(action, status="approved")
    approval.decided_by = MANAGER.user_id
    assert engine.evaluate_execution(action=action, approval=approval).rule_ids == ["A-005"]
    approval.decided_by = MANAGER2.user_id
    action.parameters = {"job_name": "flink-risk-aggregator", "checkpoint": "latest", "pin_reader_schema_version": 1}
    assert engine.evaluate_execution(action=action, approval=approval).rule_ids == ["A-006"]


def test_execution_refuses_prohibited_regardless_of_status(engine: PolicyEngine) -> None:
    action = make_action(status="approved", tool="transfer_funds", risk="high")
    assert engine.evaluate_execution(action=action, approval=None).rule_ids == ["P-002"]


def test_execution_refuses_risk_downgrade(engine: PolicyEngine) -> None:
    action = make_action(status="approved_by_policy", risk="low", requires_approval=False)
    assert engine.evaluate_execution(action=action, approval=None).rule_ids == ["E-001"]
