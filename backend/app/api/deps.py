"""Authentication, authorization and object-level access helpers (server-side enforcement)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.context import user_id_var
from app.core.errors import ApiError
from app.core.security import TokenClaims, TokenError, decode_access_token
from app.db.session import get_db
from app.models import (
    ActionRecord,
    Approval,
    Incident,
    InvestigationRun,
    KnowledgeDocument,
    RevokedToken,
    User,
)
from app.policy.engine import Actor, PolicyEngine
from app.policy.permissions import Permission, has_permission
from app.services.audit import record_audit
from app.services.container import Container

_bearer = HTTPBearer(auto_error=False)

DbDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


ContainerDep = Annotated[Container, Depends(get_container)]


@dataclass
class CurrentUser:
    user: User
    actor: Actor
    claims: TokenClaims


def get_current_user(
    db: DbDep,
    settings: SettingsDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    challenge = {"WWW-Authenticate": "Bearer"}
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise ApiError(401, "unauthenticated", "Authentication required.", headers=challenge)
    try:
        claims = decode_access_token(settings, creds.credentials)
    except TokenError as exc:
        raise ApiError(401, "invalid_token", str(exc), headers=challenge) from exc
    if db.get(RevokedToken, claims.jti) is not None:
        raise ApiError(401, "token_revoked", "Token has been revoked.", headers=challenge)
    user = db.get(User, claims.user_id)
    if (
        user is None
        or not user.is_active
        or user.tenant_id != claims.tenant_id
        or user.role != claims.role
        or (user.is_demo_account and not settings.demo_mode)
    ):
        raise ApiError(401, "invalid_token", "Invalid token.", headers=challenge)
    user_id_var.set(user.id)
    return CurrentUser(user, Actor(user.id, user.username, user.role, user.tenant_id), claims)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require(permission: Permission) -> Callable[..., CurrentUser]:
    def dependency(current: CurrentUserDep, db: DbDep) -> CurrentUser:
        if not has_permission(current.actor.role, permission):
            record_audit(db, tenant_id=current.actor.tenant_id, action="authz.denied", resource_type="permission",
                         resource_id=permission.value, outcome="denied", actor=current.actor,
                         details={"permission": permission.value})
            db.commit()
            raise ApiError(403, "forbidden", f"Your role does not permit '{permission.value}'.")
        return current

    return dependency


# ------------------------------------------------------------- object-level
def incident_or_404(db: Session, actor: Actor, incident_id: str) -> Incident:
    inc = db.get(Incident, incident_id)
    # 404 (not 403) for other tenants / insufficient clearance to avoid object enumeration.
    if inc is None or inc.tenant_id != actor.tenant_id or not PolicyEngine.can_read_classification(actor.role, inc.classification):
        raise ApiError(404, "not_found", "Incident not found.")
    return inc


def run_or_404(db: Session, actor: Actor, run_id: str) -> InvestigationRun:
    run = db.get(InvestigationRun, run_id)
    if run is None or run.tenant_id != actor.tenant_id:
        raise ApiError(404, "not_found", "Investigation not found.")
    incident_or_404(db, actor, run.incident_id)
    return run


def action_or_404(db: Session, actor: Actor, action_id: str) -> ActionRecord:
    action = db.get(ActionRecord, action_id)
    if action is None or action.tenant_id != actor.tenant_id:
        raise ApiError(404, "not_found", "Action not found.")
    incident_or_404(db, actor, action.incident_id)
    return action


def approval_or_404(db: Session, actor: Actor, approval_id: str) -> Approval:
    approval = db.get(Approval, approval_id)
    if approval is None or approval.tenant_id != actor.tenant_id:
        raise ApiError(404, "not_found", "Approval not found.")
    incident_or_404(db, actor, approval.incident_id)
    return approval


def document_or_404(db: Session, actor: Actor, doc_id: str) -> KnowledgeDocument:
    doc = db.get(KnowledgeDocument, doc_id)
    if doc is None or not PolicyEngine.can_read_document(
        actor, tenant_id=doc.tenant_id, classification=doc.classification, allowed_roles=doc.allowed_roles
    ):
        raise ApiError(404, "not_found", "Document not found.")
    return doc
