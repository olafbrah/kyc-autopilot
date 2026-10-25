import os
import random

import pytest
from fastapi.testclient import TestClient

from kyc.config import Settings
from kyc.main import build_app
from kyc.synth import make_case


@pytest.fixture
def app(tmp_path):
    url = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{tmp_path}/kyc.db"
    if url.startswith("postgresql"):
        from sqlalchemy import create_engine, text
        with create_engine(url).begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    s = Settings(database_url=url, jwt_secret="test-secret", evals_dir=tmp_path / "evals",
                 frontend_dist=tmp_path / "dist")
    return build_app(s, rng=random.Random(1))


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def as_user(client):
    tokens = {}

    def headers(sub: str) -> dict:
        if sub not in tokens:
            if sub.startswith("svc-"):
                secret = {"svc-kyc-agent": "dev-agent-secret"}.get(sub, "nope")
                r = client.post("/api/auth/token", data={"client_id": sub, "client_secret": secret})
                tokens[sub] = r.json()["access_token"]
            else:
                from kyc.auth import issue_token
                tokens[sub] = issue_token("test-secret", sub)
        return {"Authorization": f"Bearer {tokens[sub]}"}
    return headers


def case(trap: str, seed: int = 3) -> dict:
    return make_case(random.Random(seed), trap)["applicant"]


@pytest.fixture
def ingest(app):
    def _ingest(trap="clean", seed=3) -> int:
        with app.state.SessionLocal() as db:
            return app.state.ingest(db, case(trap, seed)).id
    return _ingest
