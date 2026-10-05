from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import CurrentUserDep, DbDep, SettingsDep
from app.core.errors import ApiError
from app.core.middleware import limiter
from app.core.security import create_access_token, hash_password, password_needs_rehash, verify_password
from app.db.base import utcnow
from app.models import RevokedToken, Tenant, User
from app.policy.engine import Actor
from app.policy.permissions import permissions_for
from app.schemas import GenericMessage, LoginRequest, TokenResponse, UserOut
from app.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(db: DbDep, user: User) -> dict[str, Any]:
    tenant = db.get(Tenant, user.tenant_id)
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "email": user.email,
            "role": user.role, "tenant_id": user.tenant_id, "tenant_name": tenant.name if tenant else user.tenant_id,
            "permissions": permissions_for(user.role), "is_demo_account": user.is_demo_account}


@router.post("/login", response_model=TokenResponse, summary="Exchange credentials for a short-lived bearer token")
def login(body: LoginRequest, request: Request, db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    client = (request.client.host if request.client else "unknown")
    allowed, retry = limiter.check(f"login:{client}:{body.username.lower()}", settings.login_rate_limit_per_minute)
    if not allowed:
        raise ApiError(429, "rate_limited", "Too many login attempts; try again later.", headers={"Retry-After": str(retry)})
    user = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    valid = verify_password(user.password_hash if user else None, body.password)
    if not valid or user is None or not user.is_active or (user.is_demo_account and not settings.demo_mode):
        record_audit(db, tenant_id=user.tenant_id if user else "unknown", action="auth.login_failed",
                     resource_type="user", resource_id=user.id if user else None, outcome="failure",
                     details={"username": body.username[:80]})
        db.commit()
        raise ApiError(401, "invalid_credentials", "Invalid username or password.")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    token, claims = create_access_token(settings, user_id=user.id, tenant_id=user.tenant_id, role=user.role)
    user.last_login_at = utcnow()
    record_audit(db, tenant_id=user.tenant_id, action="auth.login", resource_type="user", resource_id=user.id,
                 actor=Actor(user.id, user.username, user.role, user.tenant_id), details={"jti": claims.jti[:8]})
    db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_in": settings.access_token_ttl_minutes * 60,
            "expires_at": claims.expires_at, "user": user_out(db, user)}


@router.post("/logout", response_model=GenericMessage, summary="Revoke the current token")
def logout(current: CurrentUserDep, db: DbDep) -> dict[str, Any]:
    if db.get(RevokedToken, current.claims.jti) is None:
        db.add(RevokedToken(jti=current.claims.jti, user_id=current.user.id, expires_at=current.claims.expires_at))
    record_audit(db, tenant_id=current.actor.tenant_id, action="auth.logout", resource_type="user",
                 resource_id=current.user.id, actor=current.actor)
    db.commit()
    return {"message": "Logged out; token revoked."}


@router.get("/me", response_model=UserOut, summary="Current user, role and effective permissions")
def me(current: CurrentUserDep, db: DbDep) -> dict[str, Any]:
    return user_out(db, current.user)
