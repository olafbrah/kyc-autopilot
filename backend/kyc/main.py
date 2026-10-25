"""KYC review API. Business logic lives here; auth is kyc/auth.py, audit is kyc/audit.py, the AI rule is kyc/rules.py."""
import hmac
import json
import logging
import random
import statistics
from collections import Counter
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import Body, Depends, FastAPI, Form, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import synth
from .audit import SYSTEM, record, snapshot
from .auth import COOKIE, Policy, User, current_user, issue_token, require
from .checks import run_checks
from .config import Settings
from .db import init_db, make_engine
from .models import (AGENT_MODES, DECISIONS, AgentSettings, AiReview, Application, AuditEvent, Job, utcnow)
from .rules import auto_clear_blockers

log = logging.getLogger("kyc")
AGENT = "svc-kyc-agent"
PUBLIC_PATHS = {"/api/healthz", "/api/auth/login", "/api/auth/token", "/api/auth/personas", "/{path:path}"}


class Proposal(BaseModel):
    decision: str
    note: str


class Note(BaseModel):
    note: str = ""


class QaVerdict(BaseModel):
    verdict: str  # confirm | reopen
    note: str = ""


class ReviewIn(BaseModel):
    recommendation: str
    escalation_reason: str | None = None
    confidence: float = Field(ge=0, le=1)
    summary: str = ""
    reasons: list[str] = []
    risk_flags: list[str] = []
    agent_version: str
    model: str
    input_hash: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0


class SettingsIn(BaseModel):
    mode: str | None = None
    threshold: float | None = Field(default=None, ge=0.5, le=1.0)
    qa_rate: float | None = Field(default=None, ge=0, le=1.0)


def mask_applicant(a: dict) -> dict:
    """Data minimisation: the model never sees the full ID number or street address."""
    a = json.loads(json.dumps(a))
    num = a.get("id_document", {}).get("number", "")
    if num:
        a["id_document"]["number"] = "*" * max(len(num) - 3, 0) + num[-3:]
    a.pop("address", None)
    return a


def build_app(settings: Settings | None = None, rng: random.Random | None = None) -> FastAPI:
    settings = settings or Settings()
    rng = rng or random.Random()
    engine = make_engine(settings.database_url)
    SessionLocal = init_db(engine)

    def get_db():
        with SessionLocal() as db:
            yield db

    def agent_settings(db: Session) -> AgentSettings:
        s = db.get(AgentSettings, 1)
        if s is None:
            s = AgentSettings(id=1)
            db.add(s)
            db.flush()
        return s

    def ingest(db: Session, applicant: dict, actor=SYSTEM) -> Application:
        """Idempotent on external_id (upstream delivery is at-least-once)."""
        existing = db.scalar(select(Application).where(Application.external_id == applicant["external_id"]))
        if existing:
            return existing
        checks, tier = run_checks(applicant)
        app_ = Application(external_id=applicant["external_id"], full_name=applicant["full_name"],
                           nationality=applicant.get("nationality", ""), applicant=applicant, checks=checks,
                           risk_tier=tier, status="new")
        db.add(app_)
        try:
            db.flush()
        except IntegrityError:  # a concurrent delivery of the same external_id won the insert
            db.rollback()
            return db.scalar(select(Application).where(Application.external_id == applicant["external_id"]))
        if agent_settings(db).mode == "off":
            app_.status = "needs_review"
        record(db, actor, "application.ingest", app_, {}, details={"risk_tier": tier})
        if app_.status == "new":
            db.add(Job(application_id=app_.id))
        db.commit()
        return app_

    @asynccontextmanager
    async def lifespan(app):
        if settings.seed_demo:
            with SessionLocal() as db:
                if not db.scalar(select(func.count()).select_from(Application)):
                    for _ in range(settings.seed_demo):
                        ingest(db, synth.live_case(rng)["applicant"])
                    log.info("seeded %s demo applicants", settings.seed_demo)
        yield

    app = FastAPI(title="KYC Review", lifespan=lifespan)
    app.state.settings, app.state.policy = settings, Policy.load(settings.policy_path)
    app.state.SessionLocal, app.state.ingest = SessionLocal, ingest

    def load(db: Session, app_id: int, lock: bool = False) -> Application:
        a = db.get(Application, app_id, with_for_update=lock)
        if not a:
            raise HTTPException(404, "application not found")
        return a

    def expect(a: Application, *statuses: str):
        if a.status not in statuses:
            raise HTTPException(409, f"application is {a.status}; expected {' or '.join(statuses)}")

    def review_json(r: AiReview | None) -> dict | None:
        if r is None:
            return None
        return {k: getattr(r, k) for k in ("id", "agent_version", "model", "recommendation", "escalation_reason",
                                           "confidence", "summary", "reasons", "risk_flags", "input_hash", "latency_ms",
                                           "cost_usd", "mode", "outcome", "blockers")} | {"created_at": r.created_at.isoformat()}

    def latest_reviews(db: Session, ids: list[int]) -> dict[int, AiReview]:
        if not ids:
            return {}
        rows = db.scalars(select(AiReview).where(AiReview.application_id.in_(ids)).order_by(AiReview.id))
        return {r.application_id: r for r in rows}

    def row(a: Application, r: AiReview | None) -> dict:
        return {"id": a.id, "external_id": a.external_id, "full_name": a.full_name, "nationality": a.nationality,
                "risk_tier": a.risk_tier, "status": a.status, "assignee": a.assignee, "proposed_by": a.proposed_by,
                "decision": a.decision, "qa_status": a.qa_status, "received_at": a.received_at.isoformat(),
                "decided_at": a.decided_at.isoformat() if a.decided_at else None,
                "ai": {"recommendation": r.recommendation, "escalation_reason": r.escalation_reason,
                       "confidence": r.confidence, "outcome": r.outcome} if r else None}

    # ---------- auth ----------
    @app.get("/api/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/auth/personas")
    def personas():
        if not settings.dev_login:
            raise HTTPException(404)
        return [{"sub": sub, "name": u["name"], "roles": u.get("roles", [])}
                for sub, u in app.state.policy.users.items() if not u.get("service")]

    @app.post("/api/auth/login")
    def login(response: Response, sub: str = Body(..., embed=True)):
        user = app.state.policy.user(sub)
        if not settings.dev_login or user is None or user.service:
            raise HTTPException(400, "unknown persona")
        response.set_cookie(COOKIE, issue_token(settings.jwt_secret, sub), httponly=True, samesite="lax",
                            secure=settings.cookie_secure)
        return {"sub": sub}

    @app.post("/api/auth/token")
    def token(client_id: str = Form(...), client_secret: str = Form(...)):
        """OAuth client-credentials for service identities (the agent worker)."""
        user = app.state.policy.user(client_id)
        expected = settings.service_clients.get(client_id) or ""
        if not user or not user.service or not expected or not hmac.compare_digest(expected.encode(), client_secret.encode()):
            raise HTTPException(401, "invalid client")
        return {"access_token": issue_token(settings.jwt_secret, client_id, ttl=3600), "token_type": "bearer"}

    @app.post("/api/auth/logout")
    def logout(response: Response, user: User = Depends(current_user)):
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(user: User = Depends(current_user)):
        return {"sub": user.sub, "name": user.name, "roles": user.roles, "permissions": sorted(user.permissions)}

    # ---------- applications ----------
    @app.get("/api/applications")
    def list_applications(tab: str = "needs_review", user: User = Depends(require("kyc:read")),
                          db: Session = Depends(get_db)):
        A = Application
        where = {"needs_review": [A.status == "needs_review"],
                 "mine": [A.assignee == user.sub, A.status.in_(["in_review", "pending_approval"])],
                 "pending_approval": [A.status == "pending_approval"],
                 "auto_cleared": [A.status == "auto_cleared"],
                 "qa": [A.qa_status.is_not(None)],
                 "decided": [A.status.in_(["approved", "rejected"])],
                 "agent": [A.status == "new"],
                 "all": []}.get(tab)
        if where is None:
            raise HTTPException(422, "unknown tab")
        order = [A.decided_at.desc()] if tab in ("decided", "auto_cleared", "qa") else [A.received_at.desc()]
        if tab == "qa":
            order.insert(0, (A.qa_status != "pending"))
        apps = list(db.scalars(select(A).where(*where).order_by(*order).limit(300)))
        reviews = latest_reviews(db, [a.id for a in apps])
        counts = dict(db.execute(select(A.status, func.count()).group_by(A.status)).all())
        total = db.scalar(select(func.count()).select_from(A).where(*where))
        return {"items": [row(a, reviews.get(a.id)) for a in apps], "counts": counts, "total": total,
                "qa_pending": db.scalar(select(func.count()).select_from(A).where(A.qa_status == "pending"))}

    @app.get("/api/applications/{app_id}")
    def get_application(app_id: int, user: User = Depends(require("kyc:read")), db: Session = Depends(get_db)):
        a = load(db, app_id)
        reviews = list(db.scalars(select(AiReview).where(AiReview.application_id == a.id).order_by(AiReview.id)))
        history = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "applications",
                                                      AuditEvent.entity_id == str(a.id)).order_by(AuditEvent.id))
        return row(a, reviews[-1] if reviews else None) | {
            "applicant": a.applicant, "checks": a.checks, "decision_note": a.decision_note,
            "approved_by": a.approved_by, "qa_by": a.qa_by,
            "ai_review": review_json(reviews[-1] if reviews else None),
            "history": [{"id": e.id, "ts": e.ts.isoformat(), "actor": e.actor, "actor_type": e.actor_type,
                         "action": e.action, "outcome": e.outcome, "changes": e.changes, "details": e.details}
                        for e in history],
            "can": {"work": user.can("kyc:work"), "approve": user.can("kyc:approve"), "qa": user.can("kyc:qa")}}

    @app.post("/api/applications", status_code=201)
    def intake(applicant: dict = Body(...), user: User = Depends(require("kyc:intake")), db: Session = Depends(get_db)):
        for f in ("external_id", "full_name", "date_of_birth", "id_document"):
            if not applicant.get(f):
                raise HTTPException(422, f"missing field: {f}")
        try:
            a = ingest(db, applicant, actor=user)
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            db.rollback()
            raise HTTPException(422, f"invalid applicant data: {type(e).__name__}") from None
        return {"id": a.id, "status": a.status, "risk_tier": a.risk_tier}

    @app.post("/api/applications/{app_id}/claim")
    def claim(app_id: int, user: User = Depends(require("kyc:work")), db: Session = Depends(get_db)):
        a = load(db, app_id, lock=True)
        expect(a, "needs_review")
        before = snapshot(a)
        a.status, a.assignee = "in_review", user.sub
        record(db, user, "application.claim", a, before)
        db.commit()
        return row(a, None)

    @app.post("/api/applications/{app_id}/propose")
    def propose(app_id: int, body: Proposal, user: User = Depends(require("kyc:work")), db: Session = Depends(get_db)):
        a = load(db, app_id)
        expect(a, "in_review")
        if a.assignee != user.sub:
            raise HTTPException(409, "claim the application before proposing a decision")
        if body.decision not in DECISIONS or not body.note.strip():
            raise HTTPException(422, "a decision (approve/reject) and a justification are required")
        before = snapshot(a)
        a.status, a.decision, a.decision_note, a.proposed_by = "pending_approval", body.decision, body.note.strip(), user.sub
        record(db, user, "application.propose", a, before)
        db.commit()
        return row(a, None)

    @app.post("/api/applications/{app_id}/approve")
    def approve(app_id: int, user: User = Depends(require("kyc:approve")), db: Session = Depends(get_db)):
        a = load(db, app_id)
        expect(a, "pending_approval")
        if a.proposed_by == user.sub:
            record(db, user, "control.four_eyes_violation", entity_type="applications", entity_id=str(a.id),
                   outcome="denied")
            db.commit()
            raise HTTPException(403, "four-eyes control: you cannot approve your own proposal")
        before = snapshot(a)
        a.status = "approved" if a.decision == "approve" else "rejected"
        a.approved_by, a.decided_at = user.sub, utcnow()
        record(db, user, "application.approve", a, before)
        db.commit()
        return row(a, None)

    @app.post("/api/applications/{app_id}/send-back")
    def send_back(app_id: int, body: Note, user: User = Depends(require("kyc:approve")), db: Session = Depends(get_db)):
        a = load(db, app_id)
        expect(a, "pending_approval")
        before = snapshot(a)
        a.status, a.decision_note = "in_review", f"[sent back by {user.sub}] {body.note.strip()}"
        record(db, user, "application.send_back", a, before)
        db.commit()
        return row(a, None)

    @app.post("/api/applications/{app_id}/qa")
    def qa(app_id: int, body: QaVerdict, user: User = Depends(require("kyc:qa")), db: Session = Depends(get_db)):
        """Leads sample-check AI auto-clears. Reopening sends the case back to the human queue."""
        a = load(db, app_id)
        if a.status != "auto_cleared" or a.qa_status != "pending":
            raise HTTPException(409, "not awaiting QA")
        if body.verdict not in ("confirm", "reopen"):
            raise HTTPException(422, "verdict must be confirm or reopen")
        before = snapshot(a)
        a.qa_by = user.sub
        if body.verdict == "confirm":
            a.qa_status = "confirmed"
        else:
            a.qa_status, a.status, a.decision, a.approved_by, a.decided_at = "reopened", "needs_review", None, None, None
        record(db, user, f"application.qa_{body.verdict}", a, before, details={"note": body.note})
        db.commit()
        return row(a, None)

    # ---------- agent ----------
    @app.post("/api/agent/jobs/lease")
    def lease(user: User = Depends(require("agent:work")), db: Session = Depends(get_db)):
        """Hand the next case to a worker. SKIP LOCKED lets N workers pull concurrently; expired leases are retried."""
        if agent_settings(db).mode == "off":
            return Response(status_code=204)
        stale = utcnow() - timedelta(seconds=settings.job_lease_seconds)
        job = db.scalar(select(Job).where(or_(Job.status == "queued", (Job.status == "leased") & (Job.leased_at < stale)))
                        .order_by(Job.id).limit(1).with_for_update(skip_locked=True))
        if job is None:
            return Response(status_code=204)
        job.status, job.leased_by, job.leased_at, job.attempts = "leased", user.sub, utcnow(), job.attempts + 1
        a = db.get(Application, job.application_id)
        db.commit()
        return {"job_id": job.id, "application_id": a.id, "applicant": mask_applicant(a.applicant),
                "checks": a.checks, "risk_tier": a.risk_tier}

    @app.post("/api/applications/{app_id}/ai-review")
    def ai_review(app_id: int, body: ReviewIn, user: User = Depends(require("agent:work")),
                  db: Session = Depends(get_db)):
        """The agent submits its review; the API, not the agent, decides whether the case may be auto-cleared."""
        a = load(db, app_id, lock=True)  # serialises with the kill switch and duplicate submissions
        expect(a, "new")
        if body.recommendation not in ("approve", "escalate"):
            raise HTTPException(422, "recommendation must be approve or escalate")
        s = agent_settings(db)
        blockers = auto_clear_blockers(a.checks, a.risk_tier, a.applicant, body.model_dump(), s.threshold)
        if s.mode != "auto":
            outcome = "shadow"
        else:
            outcome = "escalated" if blockers else "auto_cleared"
        r = AiReview(application_id=a.id, mode=s.mode, outcome=outcome, blockers=blockers, **body.model_dump())
        db.add(r)
        before = snapshot(a)
        if outcome == "auto_cleared":
            a.status, a.decision, a.approved_by, a.decided_at = "auto_cleared", "approve", user.sub, utcnow()
            a.decision_note = body.summary
            if rng.random() < s.qa_rate:
                a.qa_status = "pending"
        else:
            a.status = "needs_review"
        db.flush()
        record(db, user, "application.ai_review", a, before,
               details={"outcome": outcome, "mode": s.mode, "threshold": s.threshold, "blockers": blockers,
                        "recommendation": body.recommendation, "escalation_reason": body.escalation_reason,
                        "confidence": body.confidence, "agent_version": body.agent_version, "model": body.model,
                        "input_hash": body.input_hash, "review_id": r.id, "qa_sampled": a.qa_status == "pending"})
        job = db.scalar(select(Job).where(Job.application_id == a.id))
        if job:
            job.status = "done"
        db.commit()
        return {"status": a.status, "outcome": outcome, "blockers": blockers}

    @app.get("/api/agent/settings")
    def get_settings(user: User = Depends(require("kyc:read")), db: Session = Depends(get_db)):
        s = agent_settings(db)
        db.commit()
        return {"mode": s.mode, "threshold": s.threshold, "qa_rate": s.qa_rate, "updated_by": s.updated_by,
                "updated_at": s.updated_at.isoformat()}

    @app.put("/api/agent/settings")
    def put_settings(body: SettingsIn, user: User = Depends(require("agent:admin")), db: Session = Depends(get_db)):
        s = agent_settings(db)
        if body.mode is not None and body.mode not in AGENT_MODES:
            raise HTTPException(422, f"mode must be one of {AGENT_MODES}")
        before = snapshot(s)
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(s, k, v)
        s.updated_by, s.updated_at = user.sub, utcnow()
        record(db, user, "agent.settings", s, before)
        if s.mode == "off":  # kill switch: everything waiting on the agent goes to humans now
            for a in db.scalars(select(Application).where(Application.status == "new").with_for_update()):
                b = snapshot(a)
                a.status = "needs_review"
                record(db, user, "application.kill_switch", a, b)
            for j in db.scalars(select(Job).where(Job.status != "done")):
                j.status = "done"
        db.commit()
        return get_settings(user, db)

    @app.get("/api/agent/stats")
    def stats(user: User = Depends(require("kyc:read")), db: Session = Depends(get_db)):
        A = Application
        counts = dict(db.execute(select(A.status, func.count()).group_by(A.status)).all())
        reviews = list(db.scalars(select(AiReview)))
        auto_mode = [r for r in reviews if r.mode == "auto"]
        cleared = sum(r.outcome == "auto_cleared" for r in auto_mode)
        blockers = Counter(b.split(":")[0] if b.startswith("risk_tier") else b for r in auto_mode for b in r.blockers
                           if r.outcome == "escalated")
        reasons = Counter(r.escalation_reason for r in reviews if r.recommendation == "escalate")
        now = utcnow()

        def minutes(rows):
            vals = [(x.decided_at - x.received_at).total_seconds() / 60 for x in rows if x.decided_at]
            return round(statistics.median(vals), 1) if vals else None
        auto_rows = db.scalars(select(A).where(A.status == "auto_cleared"))
        human_rows = db.scalars(select(A).where(A.status.in_(["approved", "rejected"])))
        qa = Counter(db.scalars(select(A.qa_status).where(A.qa_status.is_not(None))))
        return {"counts": counts, "reviews": len(reviews), "auto_mode_reviews": len(auto_mode), "auto_cleared": cleared,
                "auto_clear_rate": round(cleared / len(auto_mode), 3) if auto_mode else None,
                "blockers": blockers.most_common(), "escalation_reasons": reasons.most_common(),
                "reviews_last_5m": sum(r.created_at > now - timedelta(minutes=5) for r in reviews),
                "reviews_last_60m": sum(r.created_at > now - timedelta(minutes=60) for r in reviews),
                "median_minutes_to_decision": {"auto": minutes(auto_rows), "human": minutes(human_rows)},
                "cost_usd": round(sum(r.cost_usd for r in reviews), 4),
                "avg_latency_ms": round(statistics.mean(r.latency_ms for r in reviews)) if reviews else None,
                "qa": dict(qa), "agent_versions": Counter(r.agent_version for r in reviews).most_common()}

    @app.post("/api/simulate")
    def simulate(n: int = 20, user: User = Depends(require("agent:admin")), db: Session = Depends(get_db)):
        """Demo only: push N synthetic applicants as if from the onboarding system."""
        n = max(1, min(n, 500))
        for _ in range(n):
            ingest(db, synth.live_case(rng)["applicant"], actor=SYSTEM)
        return {"created": n}

    # ---------- evals ----------
    def eval_files():
        d = settings.evals_dir / "results"
        return sorted(d.glob("*.json")) if d.exists() else []

    @app.get("/api/evals")
    def evals(user: User = Depends(require("kyc:read"))):
        out = []
        for f in eval_files():
            r = json.loads(f.read_text())
            out.append({k: r.get(k) for k in ("version", "model", "backend", "change", "created_at", "metrics", "deployed")})
        return out

    @app.get("/api/evals/{version}")
    def eval_detail(version: str, user: User = Depends(require("kyc:read"))):
        f = settings.evals_dir / "results" / f"{version}.json"
        if not f.exists() or f.parent.resolve() != (settings.evals_dir / "results").resolve():
            raise HTTPException(404, "no such eval run")
        return json.loads(f.read_text())

    # ---------- frontend (public static bundle; all data is behind /api) ----------
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        dist = settings.frontend_dist
        f = (dist / path).resolve()
        if path and f.is_file() and dist.resolve() in f.parents:
            return FileResponse(f)
        index = dist / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse({"detail": "frontend not built; run `npm run build` in frontend/"}, status_code=404)

    return app


def unauthenticated_routes(app: FastAPI) -> list[str]:
    """Guardrail: every route except the explicit public ones must depend on current_user/require."""
    def deps(dependant):
        for d in dependant.dependencies:
            yield d.call
            yield from deps(d)
    bad = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if not hasattr(r, "dependant") or path in PUBLIC_PATHS:
            continue
        calls = list(deps(r.dependant))
        if not any(c is current_user or getattr(c, "__name__", "").startswith("require(") for c in calls):
            bad.append(path)
    return bad
