"""Bounded LangGraph workflow: happy path, limits, provider failures, malformed output, faults, evidence rules."""

from __future__ import annotations

import json
from typing import Any

from conftest import actor, incident, make_container
from sqlalchemy import select

from app.ai.gateway import RawCompletion
from app.ai.providers.mock import MockLLMProvider
from app.models import ActionRecord, Approval, Evidence, InvestigationEvent, LLMCall
from app.services.flags import set_fault


def start(c, db, number: str = "INC-1001", user: str = "ops.analyst", **kw):  # type: ignore[no-untyped-def]
    run = c.investigations.start(db, incident=incident(db, number), actor=actor(db, user), notes=kw.pop("notes", None),
                                 sync=True, **kw)
    db.expire_all()
    return run


class MalformedProvider(MockLLMProvider):
    name = "malformed-test"

    def complete(self, *, system: str, user: str, prompt_id: str, context: dict[str, Any], max_tokens: int) -> RawCompletion:
        if prompt_id == "triage":
            return super().complete(system=system, user=user, prompt_id=prompt_id, context=context, max_tokens=max_tokens)
        return RawCompletion("I think the renderer is broken. {not json", 10, 10, True)


class ConflictingProvider(MockLLMProvider):
    def _diagnosis(self, ctx: dict[str, Any]) -> dict[str, Any]:
        labels = [e["label"] for e in ctx["evidence"]][:2]
        mk = lambda i, rc, conf: {"id": f"H{i}", "title": rc, "description": rc, "root_cause_category": rc,  # noqa: E731
                                  "confidence": conf, "confidence_rationale": "test", "supporting_evidence": labels,
                                  "contradicting_evidence": [], "further_checks": ["Check A"]}
        return {"summary": "two", "hypotheses": [mk(1, "renderer_outage", 0.61), mk(2, "missing_template", 0.58)],
                "abstained": False, "abstention_reason": None, "conflicting_evidence": False}


class FabricatedCitationProvider(MockLLMProvider):
    def _diagnosis(self, ctx: dict[str, Any]) -> dict[str, Any]:
        out = super()._diagnosis(ctx)
        for h in out["hypotheses"]:
            h["supporting_evidence"] = ["E99", "E98"]
        return out


def test_statement_scenario_pauses_for_approval_with_evidence(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(container, db)
    assert run.status == "awaiting_approval" and run.phase == "awaiting_approval"
    state = run.state
    assert state["retrieval"]["sufficient"] is True
    top = state["diagnosis"]["hypotheses"][0]
    assert top["root_cause_category"] == "renderer_outage" and top["supporting_evidence"]
    assert state["sources"]["diagnosis"] == "mock"
    evidence = db.execute(select(Evidence).where(Evidence.investigation_id == run.id)).scalars().all()
    assert {e.kind for e in evidence} >= {"runbook", "metric", "log"}
    actions = db.execute(select(ActionRecord).where(ActionRecord.investigation_id == run.id)
                         .order_by(ActionRecord.step_index)).scalars().all()
    assert [(a.tool_name, a.status) for a in actions] == [
        ("simulate_restart_document_renderer", "pending_approval"), ("simulate_reprocess_failed_statement", "approved_by_policy")]
    approval = db.execute(select(Approval).where(Approval.action_id == actions[0].id)).scalar_one()
    assert approval.status == "pending" and set(approval.required_roles) == {"operations_manager", "demo_admin"}
    agents = {e.agent for e in db.execute(select(InvestigationEvent).where(
        InvestigationEvent.investigation_id == run.id, InvestigationEvent.event_type == "step_completed")).scalars()}
    assert {"Triage Agent", "Evidence Retrieval Agent", "Diagnostic Agent", "Remediation Planner Agent",
            "Governance/Risk Reviewer (advisory)", "Policy Engine (deterministic)"} <= agents
    assert run.step_count == 7 and run.tool_call_count > 0 and run.model_mode == "MOCK"
    assert all(c.is_mock for c in db.execute(select(LLMCall).where(LLMCall.investigation_id == run.id)).scalars())


def test_max_steps_bound_stops_safely(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(make_container(container.settings, workflow_max_steps=4), db)
    assert run.status == "failed" and run.error_code == "max_steps_exceeded" and run.outcome == "aborted"
    assert run.state["report"]["limitations"][0].startswith("Workflow stopped safely")
    assert db.execute(select(ActionRecord).where(ActionRecord.investigation_id == run.id)).first() is None


def test_tool_call_budget_enforced(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(make_container(container.settings, workflow_max_tool_calls=3), db)
    assert run.status == "failed" and run.error_code == "max_tool_calls_exceeded"
    assert run.tool_call_count <= 4


def test_token_budget_enforced(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(make_container(container.settings, workflow_token_budget=1000), db)
    assert run.status == "failed" and run.error_code == "token_budget_exceeded"
    assert run.state["report"]["generated_by"].startswith("DETERMINISTIC")


def test_malformed_model_output_never_fabricates_findings(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(make_container(container.settings, provider=MalformedProvider()), db)
    state = run.state
    assert run.status == "completed" and run.degraded
    assert state["diagnosis"]["hypotheses"] == [] and state["diagnosis"]["unavailable"] is True
    assert state["plan"]["actions"] == [] and run.outcome == "insufficient_evidence"
    errors = db.execute(select(LLMCall).where(LLMCall.investigation_id == run.id, LLMCall.status == "error")).scalars().all()
    assert errors and all(e.error_code == "malformed_output" for e in errors)


def test_provider_timeout_fault_degrades_without_fabrication(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    set_fault(db, "provider_timeout", True, None)
    db.commit()
    c = make_container(container.settings)
    run = start(c, db)
    assert run.status == "completed" and run.degraded
    assert run.state["triage"]["missing_information"] == ["AI triage unavailable; human triage required."]
    assert run.state["diagnosis"]["hypotheses"] == []
    assert db.execute(select(ActionRecord).where(ActionRecord.investigation_id == run.id)).first() is None
    assert run.state["evidence"], "deterministic evidence remains available when the model is down"


def test_retrieval_failure_fault_abstains(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    set_fault(db, "retrieval_failure", True, None)
    db.commit()
    run = start(container, db)
    assert run.state["retrieval"]["sufficient"] is False and run.state["retrieval"]["retrieval_failed"] is True
    assert run.state["diagnosis"]["abstained"] is True and run.outcome == "insufficient_evidence"
    assert "retrieval_unavailable" in run.state["degraded_reasons"]


def test_downstream_outage_fault_records_tool_errors(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    set_fault(db, "downstream_outage", True, None)
    db.commit()
    run = start(container, db)
    assert run.status == "completed" and run.degraded
    assert any(r.startswith("tool_error:get_service_health:downstream_unavailable_injected") for r in run.state["degraded_reasons"])


def test_conflicting_evidence_blocks_mutating_plan(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(make_container(container.settings, provider=ConflictingProvider()), db)
    assert run.state["diagnosis"]["conflicting_evidence"] is True
    assert run.state["plan"]["actions"] == [] and "conflicting" in run.state["plan"]["summary"]


def test_fabricated_citations_are_removed_and_force_abstention(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(make_container(container.settings, provider=FabricatedCitationProvider()), db)
    diag = run.state["diagnosis"]
    assert diag["invalid_citations_removed"] >= 2
    assert all(h["unsupported"] for h in diag["hypotheses"]) and diag["abstained"] is True
    assert run.state["plan"]["actions"] == []


def test_unknown_category_abstains(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(container, db, number="INC-1011")
    assert run.state["diagnosis"]["abstained"] is True and run.outcome == "insufficient_evidence"


def test_dry_run_creates_no_actions_or_approvals(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(container, db, execution_mode="dry_run", is_evaluation=True)
    assert run.status == "completed" and run.outcome == "dry_run"
    assert len(run.state["policy"]["decisions"]) == 2
    assert db.execute(select(ActionRecord).where(ActionRecord.investigation_id == run.id)).first() is None


def test_state_is_json_persisted_and_events_ordered(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(container, db)
    json.dumps(run.state)
    seqs = [e.seq for e in db.execute(select(InvestigationEvent).where(InvestigationEvent.investigation_id == run.id)
                                      .order_by(InvestigationEvent.seq)).scalars()]
    assert seqs == list(range(1, len(seqs) + 1)) and seqs[-1] == run.event_seq
