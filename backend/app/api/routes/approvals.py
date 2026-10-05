from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import ContainerDep, CurrentUser, DbDep, approval_or_404, require
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.api.serializers import UserCache, approval_out
from app.core.errors import ApiError
from app.domain import CLASSIFICATION_RANK, ApprovalStatus, InvestigationStatus, clearance_rank
from app.models import Approval, Incident, InvestigationRun
from app.policy.permissions import Permission
from app.schemas import ApproveRequest, CancelRequest, RejectRequest
from app.services.actions import pending_approval_count
from app.services.approvals import ApprovalError
from app.services.investigations import InvestigationError

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", summary="Approval requests (default: pending)")
def list_approvals(
    db: DbDep,
    container: ContainerDep,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    status: Annotated[ApprovalStatus | Literal["all"], Query()] = ApprovalStatus.PENDING,
    current: CurrentUser = Depends(require(Permission.APPROVALS_READ)),
) -> dict[str, Any]:
    actor = current.actor
    container.approvals.expire_stale(db, actor.tenant_id)
    allowed = [c.value for c, r in CLASSIFICATION_RANK.items() if r <= clearance_rank(actor.role)]
    q = (select(Approval).join(Incident, Incident.id == Approval.incident_id)
         .where(Approval.tenant_id == actor.tenant_id, Incident.classification.in_(allowed)))
    if status != "all":
        q = q.where(Approval.status == ApprovalStatus(status).value)
    items, total = paginate(db, q.order_by(Approval.created_at.desc()), page, page_size)
    users = UserCache(db)
    return {"items": [approval_out(db, a, users, actor, container.policy) for a in items], "total": total,
            "page": page, "page_size": page_size}


@router.get("/{approval_id}", summary="Approval detail with evidence and policy explanation")
def get_approval(approval_id: str, db: DbDep, container: ContainerDep,
                 current: CurrentUser = Depends(require(Permission.APPROVALS_READ))) -> dict[str, Any]:
    approval = approval_or_404(db, current.actor, approval_id)
    return approval_out(db, approval, UserCache(db), current.actor, container.policy)


def _maybe_resume(db: DbDep, container: ContainerDep, approval: Approval, current: CurrentUser) -> bool:
    if not approval.investigation_id or pending_approval_count(db, approval.investigation_id):
        return False
    run = db.get(InvestigationRun, approval.investigation_id)
    if run is None or run.status != InvestigationStatus.AWAITING_APPROVAL.value:
        return False
    try:
        container.investigations.resume(db, run, current.actor)
    except InvestigationError:
        return False
    return True


@router.post("/{approval_id}/approve", summary="Approve a pending simulated action (explicit confirmation required)")
def approve(approval_id: str, body: ApproveRequest, db: DbDep, container: ContainerDep,
            current: CurrentUser = Depends(require(Permission.APPROVALS_DECIDE))) -> dict[str, Any]:
    approval = approval_or_404(db, current.actor, approval_id)
    try:
        approval = container.approvals.decide(db, approval.id, current.actor, "approve",
                                              reason_code=body.reason_code.value, comment=body.comment)
    except ApprovalError as exc:
        raise ApiError(exc.http_status, exc.code, exc.message) from exc
    resumed = _maybe_resume(db, container, approval, current)
    return {**approval_out(db, approval, UserCache(db), current.actor, container.policy), "investigation_resumed": resumed}


@router.post("/{approval_id}/reject", summary="Reject a pending simulated action with a reason code")
def reject(approval_id: str, body: RejectRequest, db: DbDep, container: ContainerDep,
           current: CurrentUser = Depends(require(Permission.APPROVALS_DECIDE))) -> dict[str, Any]:
    approval = approval_or_404(db, current.actor, approval_id)
    try:
        approval = container.approvals.decide(db, approval.id, current.actor, "reject",
                                              reason_code=body.reason_code.value, comment=body.comment)
    except ApprovalError as exc:
        raise ApiError(exc.http_status, exc.code, exc.message) from exc
    resumed = _maybe_resume(db, container, approval, current)
    return {**approval_out(db, approval, UserCache(db), current.actor, container.policy), "investigation_resumed": resumed}


@router.post("/{approval_id}/cancel", summary="Cancel a pending approval request (requester or approver)")
def cancel(approval_id: str, body: CancelRequest, db: DbDep, container: ContainerDep,
           current: CurrentUser = Depends(require(Permission.APPROVALS_READ))) -> dict[str, Any]:
    approval = approval_or_404(db, current.actor, approval_id)
    try:
        approval = container.approvals.cancel(db, approval.id, current.actor, reason_code=body.reason_code.value,
                                              comment=body.comment)
    except ApprovalError as exc:
        raise ApiError(exc.http_status, exc.code, exc.message) from exc
    resumed = _maybe_resume(db, container, approval, current)
    return {**approval_out(db, approval, UserCache(db), current.actor, container.policy), "investigation_resumed": resumed}
