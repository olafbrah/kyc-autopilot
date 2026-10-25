import json

from conftest import case
from kyc.main import unauthenticated_routes

GOOD = {"recommendation": "approve", "escalation_reason": None, "confidence": 0.95, "summary": "All clear.",
        "reasons": ["Checks clear"], "risk_flags": [], "agent_version": "v1", "model": "test", "input_hash": "abc"}


def lease(client, as_user):
    r = client.post("/api/agent/jobs/lease", headers=as_user("svc-kyc-agent"))
    return r.json() if r.status_code == 200 else None


def history(client, as_user, app_id):
    return client.get(f"/api/applications/{app_id}", headers=as_user("carol")).json()["history"]


def test_every_route_is_authenticated_and_roles_are_enforced(app, client, as_user):
    assert unauthenticated_routes(app) == []
    assert client.get("/api/applications").status_code == 401
    assert client.get("/api/applications", headers=as_user("erin")).status_code == 403
    assert client.post("/api/auth/login", json={"sub": "svc-kyc-agent"}).status_code == 400  # no browser login for services
    assert client.post("/api/auth/token", data={"client_id": "svc-kyc-agent", "client_secret": "wrong"}).status_code == 401


def test_ingest_is_idempotent_and_queues_a_job(app, client, as_user, ingest):
    a, b = ingest("clean"), ingest("clean")
    assert a == b
    job = lease(client, as_user)
    assert job["application_id"] == a and lease(client, as_user) is None
    assert job["applicant"]["id_document"]["number"].startswith("***") and "address" not in job["applicant"]


def test_agent_auto_clears_only_eligible_cases_and_it_is_audited(client, as_user, ingest):
    app_id = ingest("clean")
    lease(client, as_user)
    r = client.post(f"/api/applications/{app_id}/ai-review", json=GOOD, headers=as_user("svc-kyc-agent")).json()
    assert r == {"status": "auto_cleared", "outcome": "auto_cleared", "blockers": []}
    ev = [e for e in history(client, as_user, app_id) if e["action"] == "application.ai_review"][0]
    assert ev["actor"] == "svc-kyc-agent" and ev["actor_type"] == "service"
    assert ev["changes"]["status"] == ["new", "auto_cleared"] and ev["details"]["input_hash"] == "abc"


def test_server_refuses_ai_approval_on_a_sanctions_hit(client, as_user, ingest):
    app_id = ingest("sanctions_hit")
    r = client.post(f"/api/applications/{app_id}/ai-review", json=GOOD, headers=as_user("svc-kyc-agent")).json()
    assert r["status"] == "needs_review" and "check:sanctions" in r["blockers"]


def test_injection_in_applicant_text_blocks_auto_clear_even_if_model_approves(client, as_user, ingest):
    app_id = ingest("injection", seed=6)
    r = client.post(f"/api/applications/{app_id}/ai-review", json=GOOD, headers=as_user("svc-kyc-agent")).json()
    assert r["status"] == "needs_review" and "injection_suspected" in r["blockers"]


def test_agent_cannot_do_human_actions_and_humans_cannot_submit_ai_reviews(client, as_user, ingest):
    app_id = ingest("clean")
    assert client.post(f"/api/applications/{app_id}/ai-review", json=GOOD, headers=as_user("carol")).status_code == 403
    for action in ("claim", "approve"):
        assert client.post(f"/api/applications/{app_id}/{action}", headers=as_user("svc-kyc-agent")).status_code == 403
    bad = dict(GOOD, recommendation="reject")  # the AI can never reject
    assert client.post(f"/api/applications/{app_id}/ai-review", json=bad, headers=as_user("svc-kyc-agent")).status_code == 422


def test_human_flow_with_four_eyes(client, as_user, ingest):
    app_id = ingest("vague_sof")
    client.post(f"/api/applications/{app_id}/ai-review", headers=as_user("svc-kyc-agent"),
                json=dict(GOOD, recommendation="escalate", escalation_reason="source_of_funds"))
    assert client.post(f"/api/applications/{app_id}/claim", headers=as_user("carol")).status_code == 200
    assert client.post(f"/api/applications/{app_id}/propose", headers=as_user("carol"),
                       json={"decision": "reject", "note": "Cannot evidence source of funds"}).status_code == 200
    r = client.post(f"/api/applications/{app_id}/approve", headers=as_user("carol"))
    assert r.status_code == 403 and "four-eyes" in r.json()["detail"]
    assert client.post(f"/api/applications/{app_id}/approve", headers=as_user("alice")).status_code == 403  # analyst
    assert client.post(f"/api/applications/{app_id}/approve", headers=as_user("frank")).json()["status"] == "rejected"
    actions = [e["action"] for e in history(client, as_user, app_id)]
    assert actions == ["application.ingest", "application.ai_review", "application.claim", "application.propose",
                       "control.four_eyes_violation", "application.approve"]
    cleared = ingest("clean")
    client.post(f"/api/applications/{cleared}/ai-review", headers=as_user("svc-kyc-agent"), json=GOOD)
    decided = client.get("/api/applications?tab=decided", headers=as_user("alice")).json()["items"]
    assert [a["id"] for a in decided] == [app_id]
    assert client.get("/api/applications?tab=decided", headers=as_user("alice")).json()["total"] == 1


def test_shadow_mode_never_auto_clears_and_kill_switch_routes_to_humans(client, as_user, ingest):
    assert client.put("/api/agent/settings", json={"mode": "shadow"}, headers=as_user("alice")).status_code == 403
    client.put("/api/agent/settings", json={"mode": "shadow"}, headers=as_user("carol"))
    a = ingest("clean", seed=1)
    r = client.post(f"/api/applications/{a}/ai-review", json=GOOD, headers=as_user("svc-kyc-agent")).json()
    assert r["outcome"] == "shadow" and r["status"] == "needs_review"
    b = ingest("clean", seed=2)
    client.put("/api/agent/settings", json={"mode": "off"}, headers=as_user("carol"))
    assert client.get(f"/api/applications/{b}", headers=as_user("carol")).json()["status"] == "needs_review"
    assert lease(client, as_user) is None


def test_qa_sampling_and_reopen(app, client, as_user, ingest):
    client.put("/api/agent/settings", json={"qa_rate": 1.0}, headers=as_user("carol"))
    app_id = ingest("clean")
    client.post(f"/api/applications/{app_id}/ai-review", json=GOOD, headers=as_user("svc-kyc-agent"))
    assert client.get("/api/applications?tab=qa", headers=as_user("carol")).json()["qa_pending"] == 1
    assert client.post(f"/api/applications/{app_id}/qa", json={"verdict": "reopen"}, headers=as_user("alice")).status_code == 403
    r = client.post(f"/api/applications/{app_id}/qa", json={"verdict": "reopen", "note": "check employer"},
                    headers=as_user("carol")).json()
    assert r["status"] == "needs_review" and r["qa_status"] == "reopened"


def test_audit_log_is_append_only(app, ingest):
    import pytest
    from sqlalchemy import text
    ingest("clean")
    with app.state.SessionLocal() as db, pytest.raises(Exception, match="append-only"):
        db.execute(text("DELETE FROM audit_events"))


def test_stats_and_evals_endpoints(app, client, as_user, ingest):
    app_id = ingest("clean")
    client.post(f"/api/applications/{app_id}/ai-review", json=GOOD, headers=as_user("svc-kyc-agent"))
    s = client.get("/api/agent/stats", headers=as_user("alice")).json()
    assert s["auto_clear_rate"] == 1.0 and s["counts"]["auto_cleared"] == 1
    d = app.state.settings.evals_dir / "results"
    d.mkdir(parents=True)
    (d / "v1.json").write_text(json.dumps({"version": "v1", "metrics": {"holdout": {"false_clears": 0}}, "cases": []}))
    assert client.get("/api/evals", headers=as_user("alice")).json()[0]["version"] == "v1"
    assert client.get("/api/evals/..%2Fsecret", headers=as_user("alice")).status_code == 404


def test_intake_requires_onboarding_identity(client, as_user):
    assert client.post("/api/applications", json=case("clean"), headers=as_user("carol")).status_code == 403


def test_intake_rejects_malformed_applicant(client):
    from kyc.auth import issue_token
    onboarding = {"Authorization": f"Bearer {issue_token('test-secret', 'svc-onboarding')}"}
    bad = {"external_id": "X-1", "full_name": "A B", "date_of_birth": "1990-01-01", "id_document": "not-a-dict"}
    assert client.post("/api/applications", json=bad, headers=onboarding).status_code == 422
