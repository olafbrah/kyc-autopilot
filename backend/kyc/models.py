from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

# new -> (agent) -> auto_cleared | needs_review -> in_review -> pending_approval -> approved | rejected
STATUSES = ["new", "needs_review", "in_review", "pending_approval", "approved", "rejected", "auto_cleared"]
FINAL = ("approved", "rejected", "auto_cleared")
DECISIONS = ("approve", "reject")
AGENT_MODES = ("off", "shadow", "auto")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    full_name: Mapped[str] = mapped_column(String(200))
    nationality: Mapped[str] = mapped_column(String(2))
    applicant: Mapped[dict] = mapped_column(JSON)  # everything the onboarding system sent
    checks: Mapped[dict] = mapped_column(JSON, default=dict)  # deterministic check results (kyc/checks.py)
    risk_tier: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    assignee: Mapped[str | None] = mapped_column(String(120))
    decision: Mapped[str | None] = mapped_column(String(20))
    decision_note: Mapped[str | None] = mapped_column(Text)
    proposed_by: Mapped[str | None] = mapped_column(String(120))
    approved_by: Mapped[str | None] = mapped_column(String(120))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    qa_status: Mapped[str | None] = mapped_column(String(20))  # pending | confirmed | reopened (sampled auto-clears)
    qa_by: Mapped[str | None] = mapped_column(String(120))


class AiReview(Base):
    __tablename__ = "ai_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    agent_version: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(60))
    recommendation: Mapped[str] = mapped_column(String(20))  # approve | escalate
    escalation_reason: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float)
    summary: Mapped[str] = mapped_column(Text, default="")
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list)
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    mode: Mapped[str] = mapped_column(String(10))  # agent mode when the review landed
    outcome: Mapped[str] = mapped_column(String(20))  # auto_cleared | escalated | shadow
    blockers: Mapped[list] = mapped_column(JSON, default=list)  # why the auto-clear rule said no


class Job(Base):
    """The agent's work queue. Workers lease jobs with SELECT ... FOR UPDATE SKIP LOCKED."""
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="queued", index=True)  # queued | leased | done
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    leased_by: Mapped[str | None] = mapped_column(String(120))
    leased_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentSettings(Base):
    __tablename__ = "agent_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(10), default="auto")
    threshold: Mapped[float] = mapped_column(Float, default=0.9)
    qa_rate: Mapped[float] = mapped_column(Float, default=0.05)
    updated_by: Mapped[str] = mapped_column(String(120), default="system")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditEvent(Base):
    """Append-only (DB trigger blocks UPDATE/DELETE). Written in the same transaction as the change it records."""
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(120))
    actor_type: Mapped[str] = mapped_column(String(10))  # human | service | system
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(40), index=True)
    outcome: Mapped[str] = mapped_column(String(20), default="success")
    changes: Mapped[dict] = mapped_column(JSON, default=dict)  # field -> [old, new]
    details: Mapped[dict] = mapped_column(JSON, default=dict)
