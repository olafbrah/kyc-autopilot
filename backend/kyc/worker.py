"""Agent worker: lease a case from the API, review it with the model, submit the review. Scale by running more.

It has no database credentials; it acts through the API as svc-kyc-agent, so the same permissions and
auto-clear rule apply to it as to anything else.
"""
import logging
import os
import socket
import threading
import time

import httpx

from .agent.agent import DEPLOYED_VERSION, get_config, model_error_review, review
from .agent.llm import from_env

log = logging.getLogger("kyc.worker")


class Worker:
    def __init__(self, api: str, client_id: str, secret: str, llm, cfg, http: httpx.Client | None = None):
        self.api, self.client_id, self.secret, self.llm, self.cfg = api.rstrip("/"), client_id, secret, llm, cfg
        self.http = http or httpx.Client(base_url=self.api, timeout=30)
        self.token, self.token_exp = None, 0.0
        self.lock = threading.Lock()

    def headers(self) -> dict:
        with self.lock:
            if time.time() > self.token_exp - 60:
                r = self.http.post("/api/auth/token", data={"client_id": self.client_id, "client_secret": self.secret})
                r.raise_for_status()
                self.token, self.token_exp = r.json()["access_token"], time.time() + 3600
            return {"Authorization": f"Bearer {self.token}"}

    def run_once(self) -> bool:
        r = self.http.post("/api/agent/jobs/lease", headers=self.headers())
        if r.status_code == 204:
            return False
        r.raise_for_status()
        job = r.json()
        try:
            out = review(self.llm, self.cfg, job["applicant"], job["checks"], job["risk_tier"])
        except Exception as e:  # noqa: BLE001  provider failure: fail safe to a human
            log.warning("model call failed for application %s: %s", job["application_id"], e)
            out = model_error_review(self.cfg, str(e))
        resp = self.http.post(f"/api/applications/{job['application_id']}/ai-review", json=out, headers=self.headers())
        if resp.status_code not in (200, 409):
            resp.raise_for_status()
        log.info("application %s -> %s", job["application_id"], resp.json().get("outcome", resp.json()))
        return True

    def loop(self, stop: threading.Event):
        while not stop.is_set():
            try:
                if not self.run_once():
                    stop.wait(1.0)
            except Exception:  # noqa: BLE001
                log.exception("worker iteration failed")
                stop.wait(2.0)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = get_config(os.getenv("AGENT_VERSION", DEPLOYED_VERSION), os.getenv("MODEL") or None)
    llm = from_env()
    w = Worker(os.getenv("API_URL", "http://localhost:8000"), "svc-kyc-agent",
               os.getenv("AGENT_CLIENT_SECRET", "dev-agent-secret"), llm, cfg)
    n = int(os.getenv("CONCURRENCY", "4"))
    log.info("worker %s: version=%s model=%s backend=%s concurrency=%s", socket.gethostname(), cfg.version, cfg.model,
             os.getenv("LLM_BACKEND", "simulated"), n)
    stop = threading.Event()
    threads = [threading.Thread(target=w.loop, args=(stop,), daemon=True) for _ in range(n)]
    for t in threads:
        t.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
