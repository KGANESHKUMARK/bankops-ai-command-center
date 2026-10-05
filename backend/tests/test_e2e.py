"""End-to-end demo scenarios through the HTTP API: investigate -> approve -> execute -> verify -> audit."""

from __future__ import annotations

from conftest import auth


def _start_investigation(client, headers, scenario_key: str) -> str:  # type: ignore[no-untyped-def]
    scenarios = client.get("/demo/scenarios", headers=headers).json()
    sc = next(s for s in scenarios if s["key"] == scenario_key)
    assert sc["available"] and sc["incident_id"]
    r = client.post(f"/incidents/{sc['incident_id']}/investigations", headers=headers, json={})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def _pending_approvals(detail: dict) -> list[dict]:  # type: ignore[no-untyped-def]
    return [a["approval"] for a in detail["actions"]
            if a.get("approval") and a["approval"]["status"] == "pending"]


def _approve_all(client, mgr_headers, detail: dict) -> None:  # type: ignore[no-untyped-def]
    for ap in _pending_approvals(detail):
        r = client.post(f"/approvals/{ap['id']}/approve", headers=mgr_headers,
                        json={"confirm": True, "reason_code": "EVIDENCE_SUFFICIENT"})
        assert r.status_code == 200, r.text


def test_statement_outage_full_scenario(client, clean) -> None:  # type: ignore[no-untyped-def]
    an, mgr, aud = auth(client, "ops.analyst"), auth(client, "ops.manager"), auth(client, "risk.auditor")
    run_id = _start_investigation(client, an, "statement_outage")
    detail = client.get(f"/investigations/{run_id}", headers=an).json()
    assert detail["status"] == "awaiting_approval" and detail["model_mode"] == "MOCK"
    state = detail["state"]
    runbooks = [e for e in state["evidence"] if e["kind"] == "runbook"]
    assert runbooks and all(e.get("citation") for e in runbooks)
    assert state["diagnosis"]["hypotheses"][0]["root_cause_category"] == "renderer_outage"
    pending = _pending_approvals(detail)
    assert len(pending) == 1
    restart = next(a for a in detail["actions"] if a["tool_name"] == "simulate_restart_document_renderer")
    assert restart["risk_level"] == "medium" and restart["requires_approval"] is True

    # manager approves -> auto-resume -> executed + verified -> resolved
    _approve_all(client, mgr, detail)
    detail = client.get(f"/investigations/{run_id}", headers=an).json()
    assert detail["status"] == "completed" and detail["outcome"] == "resolved"
    assert detail["state"]["report"]["title"]
    restart = next(a for a in detail["actions"] if a["tool_name"] == "simulate_restart_document_renderer")
    assert restart["status"] == "succeeded" and restart["verification_status"] == "resolved" and restart["simulated"]
    assert client.get(f"/incidents/{detail['incident_id']}", headers=an).json()["status"] == "resolved"
    # audit chain holds; auditor can inspect the trace
    assert client.get("/governance/audit/verify", headers=aud).json()["valid"] is True
    assert client.get(f"/observability/traces/{run_id}", headers=aud).status_code == 200


def test_kafka_lag_scenario_requires_approval_for_replay(client, clean) -> None:  # type: ignore[no-untyped-def]
    an, mgr = auth(client, "ops.analyst"), auth(client, "ops.manager")
    run_id = _start_investigation(client, an, "kafka_lag")
    detail = client.get(f"/investigations/{run_id}", headers=an).json()
    assert detail["status"] == "awaiting_approval"
    assert detail["state"]["diagnosis"]["hypotheses"][0]["root_cause_category"] == "consumer_processing_bottleneck"
    tools = {a["tool_name"]: a for a in detail["actions"]}
    assert "simulate_replay_dead_letter_events" in tools  # proposed, never executed silently
    assert tools["simulate_replay_dead_letter_events"]["requires_approval"] is True
    _approve_all(client, mgr, detail)
    detail = client.get(f"/investigations/{run_id}", headers=an).json()
    assert detail["status"] == "completed"


def test_schema_mismatch_scenario_controlled_remediation(client, clean) -> None:  # type: ignore[no-untyped-def]
    an, mgr = auth(client, "ops.analyst"), auth(client, "ops.manager")
    run_id = _start_investigation(client, an, "schema_mismatch")
    detail = client.get(f"/investigations/{run_id}", headers=an).json()
    assert detail["status"] == "awaiting_approval"
    assert detail["state"]["diagnosis"]["hypotheses"][0]["root_cause_category"] == "schema_mismatch"
    pending_actions = {a["tool_name"]: a for a in detail["actions"] if a.get("approval")
                       and a["approval"]["status"] == "pending"}
    assert any(a["risk_level"] == "high" for a in pending_actions.values())
    _approve_all(client, mgr, detail)
    detail = client.get(f"/investigations/{run_id}", headers=an).json()
    assert detail["status"] == "completed" and detail["outcome"] in ("resolved", "partially_resolved")


def test_demo_reset_restores_baseline(client, clean) -> None:  # type: ignore[no-untyped-def]
    an, mgr, adm = auth(client, "ops.analyst"), auth(client, "ops.manager"), auth(client, "demo.admin")
    run_id = _start_investigation(client, an, "statement_outage")
    detail = client.get(f"/investigations/{run_id}", headers=an).json()
    inc_id = detail["incident_id"]
    _approve_all(client, mgr, detail)
    assert client.get(f"/incidents/{inc_id}", headers=an).json()["status"] == "resolved"
    client.post("/demo/reset", headers=adm)
    assert client.get(f"/incidents/{inc_id}", headers=an).json()["status"] == "open"
