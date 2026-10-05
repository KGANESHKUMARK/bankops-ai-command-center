"""API contracts: auth, RBAC, object-level access, tenant isolation, validation, headers, SSE."""

from __future__ import annotations

from conftest import PASSWORD, auth, incident
from sqlalchemy import select

from app.models import Approval, Incident


def test_health_and_ready_unauthenticated(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["synthetic_data"] is True
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready" and r.json()["checks"]["database"]["ok"] is True
    for h in ("x-request-id", "x-content-type-options", "x-frame-options", "content-security-policy"):
        assert h in r.headers


def test_protected_endpoints_require_bearer(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/incidents").status_code == 401
    assert client.get("/auth/me").status_code == 401
    assert client.get("/incidents", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_login_logout_me_and_revocation(client) -> None:  # type: ignore[no-untyped-def]
    bad = client.post("/auth/login", json={"username": "ops.analyst", "password": "wrong"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_credentials"
    h = auth(client, "ops.analyst")
    me = client.get("/auth/me", headers=h).json()
    assert me["role"] == "operations_analyst" and me["tenant_id"] == "contoso-demo"
    assert "incidents:read" in me["permissions"]
    assert "demo:reset" not in me["permissions"]
    assert client.post("/auth/logout", headers=h).status_code == 200
    assert client.get("/auth/me", headers=h).status_code == 401


def test_incident_list_filters_and_pagination(client) -> None:  # type: ignore[no-untyped-def]
    h = auth(client, "ops.analyst")
    r = client.get("/incidents", headers=h, params={"status": "open", "severity": "high", "page_size": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1 and all(i["severity"] == "high" and i["status"] == "open" for i in body["items"])
    assert len(body["items"]) <= 5
    too_big = client.get("/incidents", headers=h, params={"page_size": 1000})
    assert too_big.status_code == 422


def test_tenant_isolation_idor_returns_404(client, db) -> None:  # type: ignore[no-untyped-def]
    fab_h = auth(client, "fab.analyst")
    contoso_inc = incident(db, "INC-1001")
    assert client.get(f"/incidents/{contoso_inc.id}", headers=fab_h).status_code == 404
    items = client.get("/incidents", headers=fab_h).json()["items"]
    assert items and all(i["number"].startswith("FAB-") for i in items)
    # no contoso incident leaks into the fabrikam listing
    assert contoso_inc.id not in {i["id"] for i in items}


def test_clearance_restricted_incident_not_visible_to_analyst(client, db) -> None:  # type: ignore[no-untyped-def]
    h = auth(client, "ops.analyst")
    restricted = db.execute(select(Incident).where(Incident.classification == "restricted",
                                                   Incident.tenant_id == "contoso-demo")).scalar_one()
    assert client.get(f"/incidents/{restricted.id}", headers=h).status_code == 404
    ids = {i["id"] for i in client.get("/incidents", headers=h, params={"limit": 200}).json()["items"]}
    assert restricted.id not in ids
    mgr = auth(client, "ops.manager")
    assert client.get(f"/incidents/{restricted.id}", headers=mgr).status_code == 200


def test_auditor_cannot_start_investigation_or_approve(client, db, clean) -> None:  # type: ignore[no-untyped-def]
    aud = auth(client, "risk.auditor")
    inc = incident(db, "INC-1001")
    r = client.post(f"/incidents/{inc.id}/investigations", headers=aud, json={})
    assert r.status_code == 403
    an = auth(client, "ops.analyst")
    run = client.post(f"/incidents/{inc.id}/investigations", headers=an, json={}).json()
    detail = client.get(f"/investigations/{run['id']}", headers=an).json()
    approval_id = next(a["approval"]["id"] for a in detail["actions"] if a.get("approval"))
    assert client.post(f"/approvals/{approval_id}/approve", headers=aud,
                       json={"confirm": True, "reason_code": "EVIDENCE_SUFFICIENT"}).status_code == 403


def test_read_only_role_restrictions(client) -> None:  # type: ignore[no-untyped-def]
    ro = auth(client, "readonly.viewer")
    assert client.get("/incidents", headers=ro).status_code == 200
    assert client.get("/governance/audit", headers=ro).status_code == 403
    assert client.post("/demo/reset", headers=ro).status_code == 403


def test_strict_schema_rejects_unexpected_fields(client) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/auth/login", json={"username": "ops.analyst", "password": PASSWORD, "is_admin": True})
    assert r.status_code == 422
    h = auth(client, "ops.analyst")
    r = client.post("/knowledge/search", headers=h, json={"query": "renderer", "evil_field": 1})
    assert r.status_code == 422


def test_approval_requires_explicit_confirmation(client, db, clean) -> None:  # type: ignore[no-untyped-def]
    an, mgr = auth(client, "ops.analyst"), auth(client, "ops.manager")
    inc = incident(db, "INC-1001")
    run = client.post(f"/incidents/{inc.id}/investigations", headers=an, json={}).json()
    detail = client.get(f"/investigations/{run['id']}", headers=mgr).json()
    approval_id = next(a["approval"]["id"] for a in detail["actions"] if a.get("approval"))
    no_confirm = client.post(f"/approvals/{approval_id}/approve", headers=mgr,
                             json={"confirm": False, "reason_code": "EVIDENCE_SUFFICIENT"})
    assert no_confirm.status_code == 422
    ok = client.post(f"/approvals/{approval_id}/approve", headers=mgr,
                     json={"confirm": True, "reason_code": "EVIDENCE_SUFFICIENT", "comment": "verified"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"


def test_approval_cross_tenant_idor_404(client, db, clean) -> None:  # type: ignore[no-untyped-def]
    an = auth(client, "ops.analyst")
    inc = incident(db, "INC-1001")
    run = client.post(f"/incidents/{inc.id}/investigations", headers=an, json={}).json()
    approval = db.execute(select(Approval).where(Approval.investigation_id == run["id"])).scalar_one()
    fab_mgr = auth(client, "fab.manager")
    bodies = {"approve": {"confirm": True, "reason_code": "EVIDENCE_SUFFICIENT"},
              "reject": {"reason_code": "RISK_TOO_HIGH"},
              "cancel": {"reason_code": "NO_LONGER_NEEDED"}}
    for ep, body in bodies.items():
        assert client.post(f"/approvals/{approval.id}/{ep}", headers=fab_mgr, json=body).status_code == 404


def test_request_size_limit(client) -> None:  # type: ignore[no-untyped-def]
    h = auth(client, "ops.analyst")
    huge = {"query": "x" * 2_000_000}
    assert client.post("/knowledge/search", headers=h, json=huge).status_code in (413, 422)


def test_sse_events_stream_with_last_event_id(client, db, clean) -> None:  # type: ignore[no-untyped-def]
    an = auth(client, "ops.analyst")
    inc = incident(db, "INC-1001")
    run = client.post(f"/incidents/{inc.id}/investigations", headers=an, json={}).json()
    polling = client.get(f"/investigations/{run['id']}/events", headers=an).json()
    assert polling["events"] and polling["last_seq"] == polling["events"][-1]["seq"]
    resp = client.get(f"/investigations/{run['id']}/events", headers={**an, "Accept": "text/event-stream"})
    assert resp.status_code == 200 and "text/event-stream" in resp.headers["content-type"]
    assert "event: investigation_event" in resp.text and "id: " in resp.text and "event: end" in resp.text
    resumed = client.get(f"/investigations/{run['id']}/events",
                         headers={**an, "Accept": "text/event-stream", "Last-Event-ID": "3"})
    n_full = resp.text.count("event: investigation_event")
    n_resumed = resumed.text.count("event: investigation_event")
    assert n_resumed < n_full
    # cross-tenant user cannot open the stream
    fab = auth(client, "fab.analyst")
    assert client.get(f"/investigations/{run['id']}/events",
                      headers={**fab, "Accept": "text/event-stream"}).status_code == 404


def test_demo_controls_admin_only_and_settings_safe(client, clean) -> None:  # type: ignore[no-untyped-def]
    an, adm = auth(client, "ops.analyst"), auth(client, "demo.admin")
    assert client.post("/demo/reset", headers=an).status_code == 403
    assert client.put("/demo/faults/provider_timeout", headers=an, json={"enabled": True}).status_code == 403
    assert client.post("/demo/reset", headers=adm).status_code == 200
    settings = client.get("/settings", headers=adm).json()
    assert settings["model"]["api_key"] in ("configured", "not set")
    assert "SecretStr" not in str(settings)
    assert settings["security"]["jwt_secret"] != ""


def test_knowledge_endpoints_and_search(client, clean) -> None:  # type: ignore[no-untyped-def]
    h = auth(client, "ops.analyst")
    docs = client.get("/knowledge/documents", headers=h).json()
    assert docs["total"] >= 10 and all(d["is_synthetic"] for d in docs["items"]) and docs["synthetic"] is True
    res = client.post("/knowledge/search", headers=h, json={"query": "document renderer outage restart", "top_k": 3}).json()
    assert res["results"] and res["results"][0]["citation"]
    stats = client.get("/knowledge/stats", headers=h).json()
    assert stats["documents"] >= 10 and stats["chunks"] > 0


def test_observability_and_governance_views(client, clean) -> None:  # type: ignore[no-untyped-def]
    aud = auth(client, "risk.auditor")
    assert client.get("/observability/summary", headers=aud).status_code == 200
    v = client.get("/governance/audit/verify", headers=aud).json()
    assert v["valid"] is True
    policies = client.get("/governance/policies", headers=aud).json()
    assert policies["roles"] and policies["policy_version"]
