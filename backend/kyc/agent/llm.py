"""Model access behind one interface.

Backends: OpenAI / Azure OpenAI / any OpenAI-compatible endpoint (e.g. vLLM in-cluster); replay (CI, recorded
responses); scripted (unit tests); simulated (demo without a key; heuristics, never used for eval numbers).
chat(messages, model) -> {"content": str, "usage": {...}, "model": str}
"""
import hashlib
import json
import os
import random
import threading
import time
from pathlib import Path

import httpx

# USD per 1M tokens (input, output); list prices, override with MODEL_PRICES='{"model": [in, out]}'.
PRICES = {"gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.00, 8.00), "gpt-4o": (2.50, 10.0), "gpt-4o-mini": (0.15, 0.60),
          "gpt-4.1-nano": (0.10, 0.40), "gpt-5-mini": (0.25, 2.00)}
PRICES.update({k: tuple(v) for k, v in json.loads(os.getenv("MODEL_PRICES", "{}")).items()})


def cost_usd(model: str, usage: dict) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return (usage.get("prompt_tokens", 0) * pin + usage.get("completion_tokens", 0) * pout) / 1e6


class OpenAICompatible:
    """OPENAI_API_KEY (+ OPENAI_BASE_URL for vLLM / proxies), or AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY."""

    def __init__(self, timeout: float = 60.0):
        self.azure = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY" if self.azure else "OPENAI_API_KEY", "")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.http = httpx.Client(timeout=timeout)

    def chat(self, messages: list[dict], model: str) -> dict:
        body = {"model": model, "messages": messages, "response_format": {"type": "json_object"}}
        if not model.startswith("gpt-5"):
            body.update(temperature=0, seed=7)
        if self.azure:
            url = f"{self.azure.rstrip('/')}/openai/deployments/{model}/chat/completions?api-version=2024-10-21"
            headers = {"api-key": self.api_key}
        else:
            url, headers = f"{self.base_url}/chat/completions", {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(6):
            r = self.http.post(url, json=body, headers=headers)
            if r.status_code in (429, 500, 502, 503) and attempt < 5:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            data = r.json()
            u = data.get("usage", {})
            return {"content": data["choices"][0]["message"].get("content") or "", "model": model,
                    "usage": {"prompt_tokens": u.get("prompt_tokens", 0), "completion_tokens": u.get("completion_tokens", 0)}}
        raise RuntimeError("unreachable")


class ReplayLLM:
    """Replays recorded responses keyed by a hash of the request; with `inner`, records misses (eval recording)."""

    def __init__(self, path: str | Path, inner=None):
        self.path, self.inner = Path(path), inner
        self.tape = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.lock = threading.Lock()

    @staticmethod
    def key(messages, model) -> str:
        return hashlib.sha256(json.dumps({"m": messages, "model": model}, sort_keys=True).encode()).hexdigest()[:24]

    def chat(self, messages, model):
        k = self.key(messages, model)
        if k in self.tape:
            return self.tape[k]
        if self.inner is None:
            raise KeyError(f"no recording for request {k}")
        resp = self.inner.chat(messages, model)
        with self.lock:
            self.tape[k] = resp
        return resp

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.tape, separators=(",", ":"), sort_keys=True))


class ScriptedLLM:
    """Unit tests: returns queued replies (dicts or JSON strings) or fn(messages)."""

    def __init__(self, replies=None, fn=None):
        self.replies, self.fn, self.calls = list(replies or []), fn, []

    def chat(self, messages, model="scripted"):
        self.calls.append(messages)
        r = self.fn(messages) if self.fn else self.replies.pop(0)
        return {"content": r if isinstance(r, str) else json.dumps(r), "model": model,
                "usage": {"prompt_tokens": 900, "completion_tokens": 120}}


class SimulatedLLM:
    """Demo stand-in so the stack runs without a key: realistic latency, keyword heuristics, an error rate.

    It shows the system working. It says nothing about model quality; only the eval numbers do.
    """
    VAGUE = ("various", "personal funds", "friends", "cash", "n/a", "misc", "stuff", "family abroad")
    LOW_INCOME = ("student", "unemployed", "retired", "barista", "intern", "part-time")
    BAD_MEDIA = ("fraud", "laundering", "charged", "convicted", "embezzle", "sentenced", "indicted", "ponzi")

    def __init__(self, latency: float = 0.8, error_rate: float = 0.03, seed: int | None = None):
        self.latency, self.error_rate, self.rng = latency, error_rate, random.Random(seed)

    def chat(self, messages, model="simulated"):
        import re
        time.sleep(self.latency * self.rng.uniform(0.5, 1.5))
        text = messages[-1]["content"]
        case = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))
        a, checks = case["applicant"], case["checks"]
        reason = None
        blocked = [k for k, c in checks.items() if c["status"] in ("review", "fail")]
        if blocked:
            reason = {"sanctions": "sanctions", "pep": "pep", "id_document": "document", "identity_match": "identity",
                      "country_risk": "country", "expected_volume": "volume"}.get(blocked[0], "other")
        elif any(w in (a.get("occupation") or "").lower() for w in self.LOW_INCOME) and a["expected_monthly_volume"] > 8000:
            reason = "profile"
        elif any(w in (a.get("source_of_funds") or "").lower() for w in self.VAGUE):
            reason = "source_of_funds"
        elif any(any(w in (m.get("headline", "") + m.get("snippet", "")).lower() for w in self.BAD_MEDIA)
                 and a.get("city", "").lower() in (m.get("headline", "") + m.get("snippet", "")).lower()
                 for m in a.get("adverse_media") or []):
            reason = "adverse_media"
        elif re.search(r"approve|instruction|assistant", a.get("notes") or "", re.I):
            reason = "injection"
        out = {"recommendation": "escalate" if reason else "approve", "escalation_reason": reason,
               "confidence": round(self.rng.uniform(0.9, 0.98), 2), "risk_flags": [],
               "summary": f"Simulated review: {'escalate (' + reason + ')' if reason else 'all checks clear, profile consistent'}.",
               "reasons": [c["detail"] for c in checks.values()][:3]}
        if self.rng.random() < self.error_rate:
            out["confidence"] = round(self.rng.uniform(0.5, 0.85), 2)
        return {"content": json.dumps(out), "model": model,
                "usage": {"prompt_tokens": len(text) // 4, "completion_tokens": 150}}


def from_env():
    kind = os.getenv("LLM_BACKEND", "simulated")
    if kind == "simulated":
        return SimulatedLLM(latency=float(os.getenv("SIM_LATENCY", "0.8")))
    if kind == "replay":
        return ReplayLLM(os.environ["REPLAY_CASSETTE"])
    return OpenAICompatible()
