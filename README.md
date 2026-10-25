# KYC Autopilot

A KYC (know-your-customer) review queue rebuilt as custom software, with an AI agent that clears the low-risk
applications itself and routes everything else to human analysts with a summary of why.

The point of the demo: **rebuilding an internal tool like this is the easy part. The reason to do it is to make it
better.** A Power Apps–style queue has every applicant wait for an analyst. Here most clean applicants are approved
in seconds. Humans spend their time on sanctions near-misses, PEPs, document problems and odd profiles. Every
automated decision is explainable, auditable, and gated by an eval.

```
onboarding ──POST /api/applications──► API (FastAPI) ──► Postgres
                                        │  deterministic checks → screening
                                        │  jobs table (SKIP LOCKED queue)
agent worker(s) ──lease / ai-review──►  │  server-side auto-clear rule
  └─ LLM (simulated | OpenAI-compatible)│
React UI (served by the API) ──────────►┘  humans: claim → propose → lead approves (four-eyes)
```

## Run it

```bash
docker compose up --build          # Postgres + API on :8000 + 2 agent workers, seeded with 40 applicants
open http://localhost:8000         # pick a persona: Alice/Bob (analysts), Carol/Frank (leads), Erin (no access)
```

The agent uses a **simulated model** by default (keyword heuristics with realistic latency), so the stack runs with no
API key. For a real model: `LLM_BACKEND=openai OPENAI_API_KEY=sk-... docker compose up`. Scale with `WORKERS=4`.

Local dev without Docker:

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn kyc.main:build_app --factory --reload          # SQLite by default
.venv/bin/python -m kyc.worker                                   # in another shell
cd frontend && npm install && npm run dev                        # http://localhost:5173, proxies /api
```

## Pages

| Page | Who | What |
|---|---|---|
| `/queue` | analysts, leads | Needs review · Mine · Awaiting approval · With agent · Auto-cleared · QA sample · Decided. The header shows the auto-clear rate, human queue depth, and time to decision. |
| `/applications/:id` | analysts, leads | Applicant data, automated checks, the agent's review and *why a human is needed*, actions, audit trail |
| `/agent` | everyone reads; leads change | Auto-clear rate, escalation reasons, spend/latency, QA sample. Leads: mode (auto/shadow/off), confidence threshold, QA rate, kill switch |
| `/evals` | analysts, leads | One row per agent version: false clears, auto-clear rate, recall, injection results, cost. Click a version to see the cases it got wrong. |

## How the AI is kept safe

- **Code does the hard checks** (`backend/kyc/checks.py`):
  - sanctions and PEP fuzzy screening (against a fictional watchlist standing in for a vendor)
  - ID format and expiry
  - name/DOB match against the document
  - country risk and expected volume

  These are stand-ins for vendor screening and document verification; the lists and thresholds are illustrative.
  The results roll up into a screening result: any `fail` is a **Hit**, any `review` is **Flagged**, otherwise
  **Clear** (stored as `risk_tier` high/medium/low). It is a screening summary, not a customer risk rating.
- **The model does what code can't:**
  - Does the occupation fit the expected volume?
  - Is the source of funds evasive?
  - Is the adverse media about this person or a namesake?
  - Is the applicant trying to instruct the reviewer?
- **The API, not the model, decides** (`backend/kyc/rules.py`). A case is auto-cleared only when *all* of these hold:
  - every check is clear
  - the screening result is Clear
  - the model recommends approve with confidence ≥ threshold (0.9 by default)
  - there are no risk flags
  - no instruction-like text appears in applicant fields

  Otherwise it goes to humans with the list of blockers. The model cannot reject. A wrong or compromised model can't clear a sanctions hit.
- **Data minimisation:** the model never sees the full ID number or the street address.
- **Fail safe:** if the model errors or returns unparseable output, the case goes to a human.
- **Controls for leads:**
  - shadow mode (the agent recommends, humans decide)
  - kill switch (everything waiting on the agent moves to the human queue)
  - a random QA sample of auto-clears (5% by default), which a lead confirms or reopens
- **Four-eyes** on every human decision: the approver must differ from the proposer. Violations are denied and audited.

## Auth

- **Humans** sign in through a dev persona picker that sets a signed JWT in an httpOnly cookie. It is disabled with `DEV_LOGIN=0`; the API then refuses to start unless `JWT_SECRET` and `SERVICE_CLIENTS` are set to non-default values. Set `COOKIE_SECURE=1` when serving over HTTPS.
- **The agent worker** is a service identity (`svc-kyc-agent`). It gets a token through OAuth client-credentials (`POST /api/auth/token`). It has **no database access**: it can only lease a case and submit a review through the API.
- **Permissions** come from roles in `backend/kyc/policy.yaml`. Every route declares a permission, and a test fails if any non-public route lacks one.
- **For production,** swap `auth.py` for OIDC (Entra ID / Okta): validate the IdP token against its JWKS and map groups to the same roles. Routes and tests don't change.

## Audit

- `audit_events` is append-only. Database triggers reject UPDATE/DELETE (and TRUNCATE on Postgres).
- Events are written in the same transaction as the change they describe.
- Each event records:
  - actor (human or service)
  - action
  - field-level before/after
  - for AI reviews: agent version, model, input hash, confidence, threshold, mode, and blockers
- It is shown as a timeline on each application.
- Not included (deliberately): a hash chain or a separate audit service. The internal-tools platform demo covers those.

## Agent evals

See [docs/EVALS.md](docs/EVALS.md). In short:

- **Dataset:** 300 seeded synthetic applicants, 200 dev and 100 holdout, labelled by construction with the trap they plant. Traps include sanctions near-misses, PEPs, expired IDs, implausible profiles, vague source of funds, namesake vs. real adverse media, and prompt injection.
- **Scoring:** each run scores the whole route (checks + model + rule).
- **Recording and CI:** real model responses are recorded to `backend/evals/cassettes/`. CI replays them with no key and fails on any false clear or cleared injection.

## Why no Redis

The agent queue is the `jobs` table. Workers lease with `SELECT … FOR UPDATE SKIP LOCKED`, and expired leases are retried.

- That gives concurrent workers and at-least-once delivery without another moving part.
- Ingest is idempotent on `external_id`.
- A broker (SQS, Service Bus, Kafka) can replace it behind the same two endpoints if volume ever requires it.

## What's simulated

- The watchlist, applicants and media are fictional.
- The default model is a heuristic.
- Auth is dev-only.
- Synthetic evals prove the method, not real-world accuracy. Before letting the agent clear real customers, run it in **shadow mode** against historical analyst decisions.
