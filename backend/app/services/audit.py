"""Append-only, hash-chained audit event stream.

- Each tenant has its own hash chain: hash = SHA-256(prev_hash || canonical(event)).
- ORM-level guards block UPDATE/DELETE; the migration also installs database
  triggers (SQLite and PostgreSQL) that reject UPDATE/DELETE on `audit_events`.
- Details are redacted before storage (no secrets/tokens/passwords).
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.core.context import request_id_var
from app.core.logging import get_logger, redact
from app.db.base import new_id, utcnow
from app.models import AuditEvent
from app.policy.engine import Actor, canonical_json

GENESIS_HASH = "0" * 64
log = get_logger("audit")


class AuditImmutableError(RuntimeError):
    pass


@event.listens_for(AuditEvent, "before_update")
def _block_update(*_args: Any) -> None:
    raise AuditImmutableError("audit_events is append-only")


@event.listens_for(AuditEvent, "before_delete")
def _block_delete(*_args: Any) -> None:
    raise AuditImmutableError("audit_events is append-only")


def _event_digest(prev_hash: str, fields: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical_json(fields)).encode()).hexdigest()


def _hash_fields(ev: AuditEvent) -> dict[str, Any]:
    return {
        "event_id": ev.event_id,
        "tenant_id": ev.tenant_id,
        "occurred_at": ev.occurred_at.isoformat(timespec="microseconds"),
        "actor_user_id": ev.actor_user_id,
        "actor_role": ev.actor_role,
        "action": ev.action,
        "resource_type": ev.resource_type,
        "resource_id": ev.resource_id,
        "outcome": ev.outcome,
        "investigation_id": ev.investigation_id,
        "details": ev.details,
    }


def record_audit(
    db: Session,
    *,
    tenant_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    outcome: str = "success",
    actor: Actor | None = None,
    details: dict[str, Any] | None = None,
    investigation_id: str | None = None,
) -> AuditEvent:
    """Append an audit event within the caller's transaction."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        # Serialize chain appends per tenant to prevent forks under concurrency.
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"audit:{tenant_id}"})
    db.flush()
    prev = db.execute(
        select(AuditEvent.hash).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.id.desc()).limit(1)
    ).scalar_one_or_none()
    ev = AuditEvent(
        event_id=new_id(),
        tenant_id=tenant_id,
        occurred_at=utcnow(),
        actor_user_id=actor.user_id if actor else None,
        actor_username=actor.username if actor else "system",
        actor_role=actor.role if actor else "system",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        request_id=request_id_var.get(),
        investigation_id=investigation_id,
        details=redact(details or {}),
        prev_hash=prev or GENESIS_HASH,
        hash="",
    )
    ev.hash = _event_digest(ev.prev_hash, _hash_fields(ev))
    db.add(ev)
    db.flush()
    log.info(
        "audit event",
        extra={"audit_action": action, "outcome": outcome, "resource_type": resource_type, "resource_id": resource_id},
    )
    return ev


def verify_chain(db: Session, tenant_id: str) -> dict[str, Any]:
    """Recompute the tenant's hash chain and report the first inconsistency, if any."""
    prev = GENESIS_HASH
    checked = 0
    for ev in db.execute(
        select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.id.asc())
    ).scalars():
        expected = _event_digest(prev, _hash_fields(ev))
        if ev.prev_hash != prev or ev.hash != expected:
            return {"valid": False, "checked": checked, "first_invalid_event_id": ev.event_id}
        prev = ev.hash
        checked += 1
    return {"valid": True, "checked": checked, "first_invalid_event_id": None, "head_hash": prev}
