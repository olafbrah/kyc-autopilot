"""Every change is recorded in audit_events inside the same DB transaction, so a change can't commit without its event."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from .models import AuditEvent

SYSTEM = "system"


def snapshot(obj) -> dict:
    return {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs}


def _plain(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


def diff(before: dict, after: dict, skip=("applicant", "checks")) -> dict:
    return {k: [_plain(before.get(k)), _plain(v)] for k, v in after.items()
            if k not in skip and before.get(k) != v}


def record(db: Session, actor, action: str, obj=None, before: dict | None = None, *, entity_type: str | None = None,
           entity_id: str | None = None, outcome: str = "success", details: dict | None = None) -> AuditEvent:
    """Add an audit event to the current transaction. `actor` is a User or a system name."""
    if obj is not None:
        db.flush()
    sub = getattr(actor, "sub", actor)
    actor_type = getattr(actor, "actor_type", "system")
    ev = AuditEvent(actor=sub, actor_type=actor_type, action=action,
                    entity_type=entity_type or (obj.__tablename__ if obj is not None else ""),
                    entity_id=str(entity_id if entity_id is not None else getattr(obj, "id", "")),
                    outcome=outcome, changes=diff(before or {}, snapshot(obj)) if obj is not None else {},
                    details=details or {})
    db.add(ev)
    return ev
