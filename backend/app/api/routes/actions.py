from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.agents.tools import ToolContext
from app.api.deps import ContainerDep, CurrentUser, DbDep, action_or_404, require
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.api.serializers import UserCache, action_out
from app.core.errors import ApiError
from app.domain import CLASSIFICATION_RANK, ActionStatus, RiskLevel, clearance_rank
from app.models import ActionRecord, Incident
from app.policy.catalog import ACTION_CATALOG, PROHIBITED_ACTIONS
from app.policy.permissions import Permission
from app.schemas import RollbackRequest
from app.services.actions import ActionError, ActionService

router = APIRouter(prefix="/actions", tags=["actions"])


@router.get("/catalog", summary="Allowlisted simulated tools with risk levels, targets and rollback support")
def catalog(current: CurrentUser = Depends(require(Permission.ACTIONS_READ))) -> dict[str, Any]:
    return {
        "tools": [{"name": p.tool_name, "risk_level": p.risk.value, "description": p.description,
                   "allowed_targets": list(p.allowed_targets), "rollback_supported": p.rollback_supported,
                   "rollback_note": p.rollback_note, "approver_roles": [r.value for r in p.approver_roles]}
                  for p in ACTION_CATALOG.values()],
        "prohibited": [{"name": k, "reason": v} for k, v in PROHIBITED_ACTIONS.items()],
    }


@router.get("", summary="Simulated action records (paginated)")
def list_actions(
    db: DbDep,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    status: ActionStatus | None = None,
    risk_level: RiskLevel | None = None,
    incident_id: Annotated[str | None, Query(max_length=36)] = None,
    current: CurrentUser = Depends(require(Permission.ACTIONS_READ)),
) -> dict[str, Any]:
    actor = current.actor
    allowed = [c.value for c, r in CLASSIFICATION_RANK.items() if r <= clearance_rank(actor.role)]
    q = (select(ActionRecord).join(Incident, Incident.id == ActionRecord.incident_id)
         .where(ActionRecord.tenant_id == actor.tenant_id, Incident.classification.in_(allowed)))
    if status:
        q = q.where(ActionRecord.status == status.value)
    if risk_level:
        q = q.where(ActionRecord.risk_level == risk_level.value)
    if incident_id:
        q = q.where(ActionRecord.incident_id == incident_id)
    items, total = paginate(db, q.order_by(ActionRecord.created_at.desc()), page, page_size)
    users = UserCache(db)
    incidents = {i.id: i for i in db.execute(select(Incident).where(Incident.id.in_({a.incident_id for a in items}))).scalars()}
    return {"items": [{**action_out(a, users, ActionService.approval_for(db, a.id)),
                       "incident_number": incidents[a.incident_id].number,
                       "incident_title": incidents[a.incident_id].title} for a in items],
            "total": total, "page": page, "page_size": page_size}


@router.get("/{action_id}", summary="Action detail: policy decision, approval, execution and verification")
def get_action(action_id: str, db: DbDep, current: CurrentUser = Depends(require(Permission.ACTIONS_READ))) -> dict[str, Any]:
    action = action_or_404(db, current.actor, action_id)
    incident = db.get(Incident, action.incident_id)
    return {**action_out(action, UserCache(db), ActionService.approval_for(db, action.id)),
            "incident_number": incident.number if incident else None, "incident_title": incident.title if incident else None}


@router.post("/{action_id}/verify", summary="Re-run post-action verification checks")
def verify_action(action_id: str, db: DbDep, container: ContainerDep,
                  current: CurrentUser = Depends(require(Permission.ACTIONS_VERIFY))) -> dict[str, Any]:
    action = action_or_404(db, current.actor, action_id)
    if action.status not in (ActionStatus.SUCCEEDED.value, ActionStatus.ROLLED_BACK.value, ActionStatus.FAILED.value):
        raise ApiError(409, "not_verifiable", f"Action is {action.status}; only executed actions can be verified.")
    ctx = ToolContext(db=db, actor=current.actor, settings=container.settings, retriever=container.retriever,
                      agent="Verification (manual)")
    result = container.actions.verify(db, action, actor=current.actor, ctx=ctx)
    db.refresh(action)
    return {"verification": result, "action": action_out(action, UserCache(db), ActionService.approval_for(db, action.id))}


@router.post("/{action_id}/rollback", summary="Simulated rollback where supported (explicit confirmation)")
def rollback_action(action_id: str, body: RollbackRequest, db: DbDep, container: ContainerDep,
                    current: CurrentUser = Depends(require(Permission.ACTIONS_ROLLBACK))) -> dict[str, Any]:
    action = action_or_404(db, current.actor, action_id)
    try:
        action = container.actions.rollback(db, action, actor=current.actor, reason=body.reason)
    except ActionError as exc:
        raise ApiError(exc.http_status, exc.code, exc.message) from exc
    return action_out(action, UserCache(db), ActionService.approval_for(db, action.id))
