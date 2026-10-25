import json

import httpx
from fastapi.testclient import TestClient

from kyc.agent.agent import get_config, parse
from kyc.agent.llm import ScriptedLLM
from kyc.worker import Worker


def test_worker_reviews_through_the_api(app, ingest, as_user):
    clean, injected = ingest("clean"), ingest("injection", seed=6)
    llm = ScriptedLLM(fn=lambda m: {"recommendation": "approve", "confidence": 0.97, "summary": "ok", "reasons": []})
    w = Worker("http://testserver", "svc-kyc-agent", "dev-agent-secret", llm, get_config("v1"), http=TestClient(app))
    assert w.run_once() and w.run_once() and not w.run_once()
    c = TestClient(app)
    assert c.get("/api/applications?tab=all", headers=w.headers()).status_code == 403  # agent only sees masked leases
    statuses = {i["id"]: i["status"] for i in c.get("/api/applications?tab=all", headers=as_user("alice")).json()["items"]}
    assert statuses == {clean: "auto_cleared", injected: "needs_review"}
    assert "```json" in llm.calls[0][-1]["content"] and "address" not in llm.calls[0][-1]["content"].split("```json")[1]


def test_model_failure_fails_safe_to_human(app, ingest, as_user):
    app_id = ingest("clean")

    def boom(_):
        raise httpx.ConnectError("provider down")
    w = Worker("http://testserver", "svc-kyc-agent", "dev-agent-secret", ScriptedLLM(fn=boom), get_config("v1"),
               http=TestClient(app))
    w.run_once()
    item = TestClient(app).get(f"/api/applications/{app_id}", headers=as_user("alice")).json()
    assert item["status"] == "needs_review" and "model_error" in item["ai_review"]["risk_flags"]


def test_unparseable_model_output_escalates():
    assert parse("not json")["recommendation"] == "escalate"
    assert parse(json.dumps({"recommendation": "reject"}))["risk_flags"] == ["bad_model_output"]
