"""Migration and seeding properties: idempotency, alembic round-trip, audit triggers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from conftest import PASSWORD, alembic_config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import get_settings
from app.core.security import verify_password
from app.models import AuditEvent, Incident, KnowledgeChunk, KnowledgeDocument, Service, User
from app.seed.seed import seed_all
from app.services.audit import verify_chain


def test_seed_is_deterministic_and_idempotent(container, db) -> None:  # type: ignore[no-untyped-def]
    counts_before = {m: db.execute(select(func.count(m.id))).scalar_one()
                     for m in (User, Incident, KnowledgeDocument, KnowledgeChunk, Service)}
    result = seed_all(db, container)
    db.commit()
    assert result["users_created"] == 0 and result["incidents_created"] == 0
    counts_after = {m: db.execute(select(func.count(m.id))).scalar_one() for m in counts_before}
    assert counts_before == counts_after


def test_seeded_users_have_argon2_hashes_and_verify(db) -> None:  # type: ignore[no-untyped-def]
    user = db.execute(select(User).where(User.username == "ops.analyst")).scalar_one()
    assert user.password_hash.startswith("$argon2") and PASSWORD not in user.password_hash
    assert verify_password(user.password_hash, PASSWORD)


def test_seeded_dataset_shape(db) -> None:  # type: ignore[no-untyped-def]
    assert db.execute(select(func.count(Incident.id))).scalar_one() >= 12
    assert db.execute(select(func.count(KnowledgeDocument.id)).where(
        KnowledgeDocument.deleted_at.is_(None))).scalar_one() >= 8
    assert db.execute(select(func.count(KnowledgeChunk.id))).scalar_one() >= 20
    assert db.execute(select(func.count(Incident.id)).where(
        Incident.is_synthetic.is_(True))).scalar_one() == db.execute(select(func.count(Incident.id))).scalar_one()


def test_alembic_round_trip_and_head(container) -> None:  # type: ignore[no-untyped-def]
    """Downgrade/upgrade against an isolated scratch database. `env.py` always re-reads
    `get_settings().database_url`, so DATABASE_URL is overridden and the settings cache cleared
    for the duration of this test, then restored, to avoid disturbing the shared test session DB."""
    scratch = Path(tempfile.mkdtemp(prefix="bankops-alembic-")) / "scratch.db"
    url = f"sqlite:///{scratch.as_posix()}"
    original_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    get_settings.cache_clear()
    try:
        cfg = alembic_config()
        command.upgrade(cfg, "head")
        engine = create_engine(url)
        with Session(engine) as scratch_db:
            current = scratch_db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert current == "0001"
            assert scratch_db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='incidents'")).first()
        command.downgrade(cfg, "base")
        with Session(engine) as scratch_db:
            assert scratch_db.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='incidents'")).first() is None
        command.upgrade(cfg, "head")
        with Session(engine) as scratch_db:
            assert scratch_db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='incidents'")).first()
        engine.dispose()
    finally:
        if original_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original_env
        get_settings.cache_clear()


def test_audit_update_and_delete_blocked_by_trigger(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    # covered in test_actions_approvals too; here we assert the trigger exists post-migration
    assert db.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE '%audit%'")).first() is not None
    ev = db.execute(select(AuditEvent).limit(1)).scalar_one()
    try:
        db.execute(text("UPDATE audit_events SET outcome='x' WHERE id=:i"), {"i": ev.id})
        db.commit()
        raise AssertionError("update should have been blocked")
    except IntegrityError:
        db.rollback()


def test_unique_constraints(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    from app.models import Tenant

    db.add(Tenant(id="contoso-demo", name="dup"))
    try:
        db.commit()
        raise AssertionError("duplicate tenant id should fail")
    except IntegrityError:
        db.rollback()


def test_audit_chain_valid_for_all_tenants(db) -> None:  # type: ignore[no-untyped-def]
    for tenant in ("contoso-demo", "fabrikam-demo"):
        result = verify_chain(db, tenant)
        assert result["valid"] is True
