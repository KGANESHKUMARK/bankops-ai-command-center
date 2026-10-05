from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app import __version__
from app.api.deps import ContainerDep, CurrentUser, DbDep, SettingsDep, require
from app.core.errors import ApiError
from app.core.middleware import limiter
from app.domain import Role
from app.models import Incident, User
from app.policy.permissions import Permission
from app.schemas import FaultRequest
from app.seed.scenarios import SCENARIOS
from app.seed.seed import reset_demo
from app.services.audit import record_audit
from app.services.flags import FAULTS, get_faults, set_fault

router = APIRouter(tags=["demo"])


def _require_demo_mode(settings: SettingsDep) -> None:
    if not settings.demo_mode or settings.is_production_like:
        raise ApiError(403, "demo_disabled", "Demo controls are only available in local/demo mode.")


@router.get("/demo/scenarios", summary="Guided demo scenarios")
def scenarios(db: DbDep, current: CurrentUser = Depends(require(Permission.INCIDENTS_READ))) -> list[dict[str, Any]]:
    out = []
    for sc in SCENARIOS:
        inc = db.execute(select(Incident).where(Incident.tenant_id == current.actor.tenant_id,
                                                Incident.number == sc["incident_number"])).scalar_one_or_none()
        out.append({**sc, "incident_id": inc.id if inc else None, "incident_status": inc.status if inc else None,
                    "available": inc is not None})
    return out


@router.get("/demo/accounts", summary="Demo account usernames and roles (local/demo mode only; no passwords)")
def demo_accounts(db: DbDep, settings: SettingsDep) -> list[dict[str, Any]]:
    if not settings.demo_mode or settings.is_production_like:
        return []
    rows = db.execute(select(User).where(User.is_demo_account.is_(True), User.is_active.is_(True))
                      .order_by(User.tenant_id, User.username)).scalars()
    return [{"username": u.username, "role": u.role, "tenant_id": u.tenant_id, "display_name": u.display_name}
            for u in rows]


@router.post("/demo/reset", summary="Reset synthetic demo state (demo_admin, local/demo mode only)")
def demo_reset(db: DbDep, settings: SettingsDep, container: ContainerDep,
               current: CurrentUser = Depends(require(Permission.DEMO_RESET))) -> dict[str, Any]:
    _require_demo_mode(settings)
    if current.actor.role != Role.DEMO_ADMIN:
        raise ApiError(403, "forbidden", "Only the demo administrator may reset the demo.")
    summary = reset_demo(db, container, actor=current.actor)
    limiter.reset()
    return {"message": "Synthetic demo state reset to the seeded baseline.", "summary": summary}


@router.get("/demo/faults", summary="Failure-injection flags")
def faults(db: DbDep, current: CurrentUser = Depends(require(Permission.OBSERVABILITY_READ))) -> dict[str, Any]:
    return {"faults": get_faults(db), "descriptions": FAULTS}


@router.put("/demo/faults/{name}", summary="Toggle a failure-injection flag (demo_admin, local/demo mode only)")
def toggle_fault(name: str, body: FaultRequest, db: DbDep, settings: SettingsDep,
                 current: CurrentUser = Depends(require(Permission.DEMO_FAULTS))) -> dict[str, Any]:
    _require_demo_mode(settings)
    if name not in FAULTS:
        raise ApiError(404, "not_found", "Unknown fault.")
    set_fault(db, name, body.enabled, current.actor.user_id)
    record_audit(db, tenant_id=current.actor.tenant_id, action="demo.fault_toggled", resource_type="fault",
                 resource_id=name, actor=current.actor, details={"enabled": body.enabled})
    db.commit()
    return {"faults": get_faults(db), "descriptions": FAULTS}


@router.get("/settings", summary="Safe configuration view (secrets are never returned)")
def settings_view(settings: SettingsDep, container: ContainerDep,
                  current: CurrentUser = Depends(require(Permission.SETTINGS_READ))) -> dict[str, Any]:
    s = settings

    def secret_state(value: Any) -> str:
        return "configured" if value is not None and value.get_secret_value() else "not set"

    return {
        "version": __version__, "environment": s.app_env, "demo_mode": s.demo_mode, "synthetic_data": True,
        "model": {**container.gateway.status(), "mock_mode": container.gateway.provider.is_mock,
                  "configured_provider": s.llm_provider, "configured_model": s.llm_model,
                  "approved_models": s.llm_approved_models, "base_url_configured": bool(s.llm_base_url),
                  "api_key": secret_state(s.llm_api_key), "timeout_seconds": s.llm_timeout_seconds,
                  "max_retries": s.llm_max_retries, "judge_enabled": s.llm_judge_enabled},
        "embedding": {"provider": s.embedding_provider, "model": container.embedder.model, "dim": s.embedding_dim,
                      "api_key": secret_state(s.embedding_api_key)},
        "storage": {"database": "sqlite (local fallback)" if s.is_sqlite else "postgresql",
                    "vector_backend": s.vector_backend, "index_version": s.index_version},
        "security": {"jwt_secret": "configured" if s.jwt_secret else "ephemeral (local only)",
                     "access_token_ttl_minutes": s.access_token_ttl_minutes, "cors_allowed_origins": s.cors_allowed_origins,
                     "max_request_body_bytes": s.max_request_body_bytes, "max_upload_bytes": s.max_upload_bytes,
                     "rate_limit_per_minute": s.rate_limit_per_minute, "login_rate_limit_per_minute": s.login_rate_limit_per_minute,
                     "demo_password": "set (local-only)" if s.demo_password else "not set"},
        "workflow": {"max_steps": s.workflow_max_steps, "max_tool_calls": s.workflow_max_tool_calls,
                     "token_budget": s.workflow_token_budget, "step_timeout_seconds": s.workflow_step_timeout_seconds,
                     "total_timeout_seconds": s.workflow_total_timeout_seconds, "execution_mode": s.workflow_execution_mode},
        "policy": {"medium_risk_requires_approval": s.medium_risk_requires_approval,
                   "low_risk_requires_approval": s.low_risk_requires_approval, "approval_ttl_minutes": s.approval_ttl_minutes},
        "can_reset_demo": current.actor.role == Role.DEMO_ADMIN and s.demo_mode and not s.is_production_like,
        "can_toggle_faults": current.actor.role == Role.DEMO_ADMIN and s.demo_mode and not s.is_production_like,
    }
