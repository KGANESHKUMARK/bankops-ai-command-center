"""FastAPI application factory for BankOps AI Command Center (SYNTHETIC DEMO)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError

from app import __version__
from app.api.routes import (
    actions,
    approvals,
    auth,
    dashboard,
    demo,
    evaluations,
    governance,
    health,
    incidents,
    investigations,
    knowledge,
    observability,
)
from app.core.config import InsecureConfigurationError, Settings, get_settings, validate_startup_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import BodySizeLimitMiddleware, RateLimitMiddleware, RequestContextMiddleware
from app.models import User
from app.services.container import Container, build_container

log = get_logger("app")

DESCRIPTION = """
**SYNTHETIC DEMO - not a production banking system.** Governed RAG, bounded multi-agent investigation,
deterministic policy engine, human approval, simulated remediation, verification, audit, evaluation and
observability. All data is fictional; all remediation is simulated against seeded demo state.
"""


def enforce_production_safety(container: Container) -> None:
    settings = container.settings
    if not settings.is_production_like:
        return
    with container.session_factory() as db:
        demo_active = db.execute(select(User.id).where(User.is_demo_account.is_(True), User.is_active.is_(True))).first()
    if demo_active:
        raise InsecureConfigurationError("Active demo accounts exist; deactivate them before starting in staging/production.")


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()
    for warning in validate_startup_settings(settings):
        log.warning(warning)
    container = container or build_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        enforce_production_safety(container)
        try:
            with container.session_factory() as db:
                recovered = container.investigations.recover_stale(db)
                if recovered:
                    log.warning("marked orphaned investigations as interrupted", extra={"count": recovered})
                from app.seed.seed import register_versions, seed_all

                if settings.seed_on_startup:
                    seed_all(db, container)
                register_versions(db, container)
        except (OperationalError, ProgrammingError) as exc:
            log.error("database not ready - run `alembic upgrade head`", extra={"error_code": type(exc).__name__})
        log.info("startup complete", extra={"environment": settings.app_env, "model_mode": container.gateway.mode,
                                            "vector_backend": settings.vector_backend})
        yield
        log.info("shutting down: waiting for in-flight investigations")
        container.shutdown()

    app = FastAPI(
        title="BankOps AI Command Center API (SYNTHETIC DEMO)",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs" if settings.expose_api_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.expose_api_docs else None,
    )
    app.state.container = container
    install_error_handlers(app)
    # Added inner -> outer: body limit, rate limit, CORS, request context (outermost).
    app.add_middleware(BodySizeLimitMiddleware, settings=settings)
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o for o in settings.cors_allowed_origins if o != "*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Correlation-ID", "Last-Event-ID", "Accept"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware, metrics=container.metrics, settings=settings)
    for module in (health, auth, dashboard, incidents, investigations, approvals, actions, knowledge, governance,
                   evaluations, observability, demo):
        app.include_router(module.router)
    return app


app = create_app()
