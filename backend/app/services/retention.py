"""Data retention: purge expired soft-deleted documents, expired revocations and old evaluation runs.

Audit events are append-only and are never purged by the application; archival to
immutable (WORM) storage is documented as future production work.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import utcnow
from app.models import InvestigationRun, KnowledgeDocument, RevokedToken
from app.policy.engine import Actor
from app.services.audit import record_audit


def retention_policy(settings: Settings) -> dict[str, Any]:
    return {
        "deleted_documents_days": settings.retention_deleted_documents_days,
        "evaluation_investigations_days": settings.retention_investigations_days,
        "audit_events_days": settings.retention_audit_days,
        "audit_note": "Audit events are append-only (DB triggers) and never purged by the app; production would archive "
                      "them to WORM storage after the retention period.",
        "revoked_tokens": "Purged after the token's own expiry.",
    }


def _candidates(db: Session, settings: Settings, tenant_id: str) -> dict[str, list[Any]]:
    now = utcnow()
    docs = db.execute(select(KnowledgeDocument).where(KnowledgeDocument.tenant_id == tenant_id,
                                                      KnowledgeDocument.deleted_at.is_not(None),
                                                      KnowledgeDocument.retention_until < now)).scalars().all()
    runs = db.execute(select(InvestigationRun).where(
        InvestigationRun.tenant_id == tenant_id, InvestigationRun.is_evaluation.is_(True),
        InvestigationRun.created_at < now - timedelta(days=settings.retention_investigations_days))).scalars().all()
    tokens = db.execute(select(RevokedToken).where(RevokedToken.expires_at < now)).scalars().all()
    return {"documents": list(docs), "evaluation_runs": list(runs), "revoked_tokens": list(tokens)}


def retention_report(db: Session, settings: Settings, tenant_id: str) -> dict[str, Any]:
    c = _candidates(db, settings, tenant_id)
    return {"policy": retention_policy(settings), "candidates": {k: len(v) for k, v in c.items()}}


def apply_retention(db: Session, settings: Settings, actor: Actor, *, dry_run: bool) -> dict[str, Any]:
    c = _candidates(db, settings, actor.tenant_id)
    counts = {k: len(v) for k, v in c.items()}
    if not dry_run:
        for doc in c["documents"]:
            db.delete(doc)
        for run in c["evaluation_runs"]:
            db.delete(run)
        if c["revoked_tokens"]:
            db.execute(delete(RevokedToken).where(RevokedToken.jti.in_([t.jti for t in c["revoked_tokens"]])))
    record_audit(db, tenant_id=actor.tenant_id, action="retention.applied" if not dry_run else "retention.dry_run",
                 resource_type="retention", actor=actor, details={"counts": counts, "dry_run": dry_run})
    db.commit()
    return {"dry_run": dry_run, "purged" if not dry_run else "would_purge": counts}
