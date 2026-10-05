from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import ContainerDep, CurrentUser, DbDep, require, run_or_404
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.api.serializers import UserCache, event_out, run_out
from app.core.errors import ApiError
from app.domain import CLASSIFICATION_RANK, InvestigationStatus, clearance_rank
from app.models import Incident, InvestigationEvent, InvestigationRun
from app.policy.permissions import Permission
from app.schemas import CancelInvestigationRequest
from app.services.investigations import InvestigationError

router = APIRouter(prefix="/investigations", tags=["investigations"])
STREAM_END_STATES = {InvestigationStatus.COMPLETED.value, InvestigationStatus.FAILED.value,
                     InvestigationStatus.CANCELLED.value, InvestigationStatus.AWAITING_APPROVAL.value,
                     InvestigationStatus.INTERRUPTED.value}


@router.get("", summary="List investigations visible to the caller (paginated)")
def list_investigations(
    db: DbDep,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    incident_id: Annotated[str | None, Query(max_length=36)] = None,
    status: InvestigationStatus | None = None,
    include_evaluation: bool = False,
    current: CurrentUser = Depends(require(Permission.INVESTIGATIONS_READ)),
) -> dict[str, Any]:
    actor = current.actor
    allowed = [c.value for c, r in CLASSIFICATION_RANK.items() if r <= clearance_rank(actor.role)]
    q = (select(InvestigationRun).join(Incident, Incident.id == InvestigationRun.incident_id)
         .where(InvestigationRun.tenant_id == actor.tenant_id, Incident.classification.in_(allowed)))
    if not include_evaluation:
        q = q.where(InvestigationRun.is_evaluation.is_(False))
    if incident_id:
        q = q.where(InvestigationRun.incident_id == incident_id)
    if status:
        q = q.where(InvestigationRun.status == status.value)
    items, total = paginate(db, q.order_by(InvestigationRun.created_at.desc()), page, page_size)
    users = UserCache(db)
    return {"items": [run_out(db, r, users, include_state=False) for r in items], "total": total, "page": page,
            "page_size": page_size}


@router.get("/{investigation_id}", summary="Investigation state, evidence, hypotheses, plan, policy and report")
def get_investigation(investigation_id: str, db: DbDep, container: ContainerDep,
                      current: CurrentUser = Depends(require(Permission.INVESTIGATIONS_READ))) -> dict[str, Any]:
    run = run_or_404(db, current.actor, investigation_id)
    return run_out(db, run, UserCache(db), include_state=True, settings=container.settings)


def _fetch(container: ContainerDep, run_id: str, after: int) -> tuple[list[dict[str, Any]], str]:
    with container.session_factory() as db:
        rows = db.execute(select(InvestigationEvent).where(InvestigationEvent.investigation_id == run_id,
                                                           InvestigationEvent.seq > after)
                          .order_by(InvestigationEvent.seq).limit(200)).scalars().all()
        run = db.get(InvestigationRun, run_id)
        return [event_out(r) for r in rows], run.status if run else InvestigationStatus.FAILED.value


@router.get("/{investigation_id}/events",
            summary="Investigation events: JSON (polling, ?after=seq) or SSE (Accept: text/event-stream)")
async def investigation_events(
    investigation_id: str,
    request: Request,
    db: DbDep,
    container: ContainerDep,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    current: CurrentUser = Depends(require(Permission.INVESTIGATIONS_READ)),
) -> Any:
    run = run_or_404(db, current.actor, investigation_id)  # object-level authorization before any event is sent
    if last_event_id and last_event_id.isdigit():
        after = max(after, int(last_event_id))
    if "text/event-stream" not in request.headers.get("accept", ""):
        events, status = await run_in_threadpool(_fetch, container, run.id, after)
        return {"investigation_id": run.id, "status": status, "events": events,
                "last_seq": events[-1]["seq"] if events else after}

    token_expiry = current.claims.expires_at

    async def stream() -> AsyncIterator[str]:
        last = after
        started = time.monotonic()
        last_beat = started
        yield "retry: 3000\n\n"
        while True:
            if await request.is_disconnected():
                return
            if datetime.now(UTC) >= token_expiry:
                yield "event: auth_expired\ndata: {}\n\n"
                return
            events, status = await run_in_threadpool(_fetch, container, run.id, last)
            for ev in events:
                last = ev["seq"]
                yield f"id: {ev['seq']}\nevent: investigation_event\ndata: {json.dumps(ev, default=str)}\n\n"
            if not events and status in STREAM_END_STATES:
                yield f"event: end\ndata: {json.dumps({'status': status, 'last_seq': last})}\n\n"
                return
            now = time.monotonic()
            if now - started > 300:
                yield "event: reconnect\ndata: {}\n\n"
                return
            if now - last_beat > 15:
                last_beat = now
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{investigation_id}/resume", status_code=202, summary="Resume after approvals are decided")
def resume_investigation(investigation_id: str, db: DbDep, container: ContainerDep,
                         current: CurrentUser = Depends(require(Permission.INVESTIGATIONS_RESUME))) -> dict[str, Any]:
    run = run_or_404(db, current.actor, investigation_id)
    try:
        run = container.investigations.resume(db, run, current.actor)
    except InvestigationError as exc:
        raise ApiError(exc.http_status, exc.code, exc.message) from exc
    return run_out(db, run, UserCache(db), include_state=True, settings=container.settings)


@router.post("/{investigation_id}/cancel", summary="Cancel a queued, running or awaiting investigation")
def cancel_investigation(investigation_id: str, body: CancelInvestigationRequest, db: DbDep, container: ContainerDep,
                         current: CurrentUser = Depends(require(Permission.INVESTIGATIONS_START))) -> dict[str, Any]:
    run = run_or_404(db, current.actor, investigation_id)
    try:
        run = container.investigations.cancel(db, run, current.actor, body.reason)
    except InvestigationError as exc:
        raise ApiError(exc.http_status, exc.code, exc.message) from exc
    return run_out(db, run, UserCache(db), include_state=True, settings=container.settings)
