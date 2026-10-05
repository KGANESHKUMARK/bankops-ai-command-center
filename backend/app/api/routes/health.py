from __future__ import annotations

from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text

from app import __version__
from app.api.deps import ContainerDep, DbDep, SettingsDep
from app.core.config import BACKEND_DIR
from app.models import KnowledgeChunk
from app.schemas import HealthOut

router = APIRouter(tags=["health"])


def _alembic_head() -> str | None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


@router.get("/health", response_model=HealthOut, summary="Liveness probe")
def health(settings: SettingsDep) -> dict[str, Any]:
    return {"status": "ok", "version": __version__, "environment": settings.app_env, "synthetic_data": True}


@router.get("/ready", summary="Readiness probe (database, migrations, index, model gateway)")
def ready(db: DbDep, settings: SettingsDep, container: ContainerDep) -> JSONResponse:
    checks: dict[str, Any] = {}
    ok = True
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True, "backend": "sqlite" if settings.is_sqlite else "postgresql"}
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"ok": False, "error": type(exc).__name__}
        return JSONResponse({"status": "not_ready", "checks": checks}, status_code=503)
    try:
        current = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        head = _alembic_head()
        checks["migrations"] = {"ok": current == head, "current": current, "head": head}
        ok &= current == head
    except Exception as exc:  # noqa: BLE001
        checks["migrations"] = {"ok": False, "error": type(exc).__name__}
        ok = False
    chunks = db.execute(select(func.count(KnowledgeChunk.id)).where(
        KnowledgeChunk.index_version == settings.index_version)).scalar_one()
    checks["knowledge_index"] = {"ok": chunks > 0, "current_index_chunks": int(chunks),
                                 "index_version": settings.index_version, "vector_backend": settings.vector_backend}
    gateway = container.gateway.status()
    checks["model_gateway"] = {"ok": gateway["circuit_breaker"] != "open", **gateway}
    # Knowledge and model issues degrade the service but do not make it unready (incident access still works).
    status = "ready" if ok and chunks > 0 and gateway["circuit_breaker"] != "open" else ("degraded" if ok else "not_ready")
    return JSONResponse({"status": status, "checks": checks}, status_code=200 if ok else 503)
