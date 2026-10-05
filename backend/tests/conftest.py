"""Test fixtures. Environment is configured BEFORE any app module is imported."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="bankops-tests-"))
os.environ.update(
    APP_ENV="test",
    DEMO_MODE="true",
    DATABASE_URL=f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    DEMO_PASSWORD="test-demo-password-123",
    JWT_SECRET="test-jwt-secret-that-is-long-enough-0123456789",
    WORKFLOW_EXECUTION_MODE="sync",
    LLM_PROVIDER="mock",
    EMBEDDING_PROVIDER="hashing",
    RATE_LIMIT_PER_MINUTE="100000",
    LOGIN_RATE_LIMIT_PER_MINUTE="100000",
    SEED_ON_STARTUP="false",
)

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import BACKEND_DIR, Settings, get_settings  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.models import Incident, User  # noqa: E402
from app.policy.engine import Actor  # noqa: E402
from app.services.container import Container, build_container  # noqa: E402

PASSWORD = "test-demo-password-123"


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def container(settings: Settings) -> Iterator[Container]:
    command.upgrade(alembic_config(), "head")
    c = build_container(settings)
    from app.seed.seed import seed_all

    with get_session_factory()() as db:
        seed_all(db, c)
    yield c
    c.shutdown()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture
def db(container: Container) -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def clean(container: Container) -> None:
    """Restore the seeded synthetic baseline before a state-mutating test."""
    from app.seed.seed import reset_demo

    with get_session_factory()() as session:
        reset_demo(session, container, actor=None)


@pytest.fixture(scope="session")
def app(container: Container):  # type: ignore[no-untyped-def]
    from app.main import create_app

    return create_app(container.settings, container)


@pytest.fixture
def client(app) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    with TestClient(app) as c:
        yield c


def actor(db: Session, username: str) -> Actor:
    user = db.execute(select(User).where(User.username == username)).scalar_one()
    return Actor(user.id, user.username, user.role, user.tenant_id)


def incident(db: Session, number: str, tenant: str = "contoso-demo") -> Incident:
    return db.execute(select(Incident).where(Incident.number == number, Incident.tenant_id == tenant)).scalar_one()


def auth(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def make_container(base: Settings, provider=None, **overrides) -> Container:  # type: ignore[no-untyped-def]
    return build_container(base.model_copy(update={"workflow_execution_mode": "sync", **overrides}), provider=provider)
