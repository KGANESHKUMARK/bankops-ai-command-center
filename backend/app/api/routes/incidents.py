from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import case, or_, select

from app.api.deps import ContainerDep, CurrentUser, DbDep, incident_or_404, require
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.api.serializers import UserCache, incident_summary, run_out, service_keys
from app.core.errors import ApiError
from app.domain import CLASSIFICATION_RANK, IncidentStatus, Severity, clearance_rank
from app.models import Incident, IncidentEvent, InvestigationRun, LogEvent, Service, ServiceDependency
from app.policy.permissions import Permission, has_permission
from app.rag.injection import neutralize
from app.schemas import StartInvestigationRequest
from app.services.investigations import InvestigationError

router = APIRouter(tags=["incidents"])


@router.get("/services", summary="Synthetic service catalog with live simulated status")
def list_services(db: DbDep, current: CurrentUser = Depends(require(Permission.INCIDENTS_READ))) -> list[dict[str, Any]]:
    rows = db.execute(select(Service).where(Service.tenant_id == current.actor.tenant_id).order_by(Service.key)).scalars()
    return [{"key": s.key, "name": s.name, "status": s.status, "tier": s.tier, "owner_team": s.owner_team} for s in rows]


@router.get("/incidents", summary="Search and filter incidents (paginated)")
def list_incidents(
    db: DbDep,
    page: PageParam = 1,
    page_size: PageSizeParam = 20,
    search: Annotated[str | None, Query(max_length=100)] = None,
    severity: Severity | None = None,
    status_filter: Annotated[IncidentStatus | None, Query(alias="status")] = None,
    category: Annotated[str | None, Query(max_length=64, pattern=r"^[a-z_]+$")] = None,
    service: Annotated[str | None, Query(max_length=64, pattern=r"^[a-z0-9\-]+$")] = None,
    open_only: bool = False,
    sort: Literal["detected_desc", "detected_asc", "severity"] = "detected_desc",
    current: CurrentUser = Depends(require(Permission.INCIDENTS_READ)),
) -> dict[str, Any]:
    actor = current.actor
    allowed = [c.value for c, r in CLASSIFICATION_RANK.items() if r <= clearance_rank(actor.role)]
    q = select(Incident).where(Incident.tenant_id == actor.tenant_id, Incident.classification.in_(allowed))
    if search:
        term = f"%{search.strip()}%"  # bound parameter - no SQL injection
        q = q.where(or_(Incident.title.ilike(term), Incident.number.ilike(term), Incident.description.ilike(term)))
    if severity:
        q = q.where(Incident.severity == severity.value)
    if status_filter:
        q = q.where(Incident.status == status_filter.value)
    if open_only:
        q = q.where(Incident.status.in_(["open", "investigating", "awaiting_approval", "mitigated"]))
    if category:
        q = q.where(Incident.category == category)
    if service:
        svc = db.execute(select(Service).where(Service.tenant_id == actor.tenant_id, Service.key == service)).scalar_one_or_none()
        q = q.where(Incident.primary_service_id == (svc.id if svc else "__none__"))
    if sort == "detected_asc":
        q = q.order_by(Incident.detected_at.asc())
    elif sort == "severity":
        q = q.order_by(case({"critical": 0, "high": 1, "medium": 2, "low": 3}, value=Incident.severity), Incident.detected_at.desc())
    else:
        q = q.order_by(Incident.detected_at.desc())
    items, total = paginate(db, q, page, page_size)
    services = service_keys(db, actor.tenant_id)
    return {"items": [incident_summary(i, services) for i in items], "total": total, "page": page,
            "page_size": page_size, "synthetic": True}


@router.get("/incidents/{incident_id}", summary="Incident detail: timeline, logs, dependencies, history")
def get_incident(incident_id: str, db: DbDep, container: ContainerDep,
                 current: CurrentUser = Depends(require(Permission.INCIDENTS_READ))) -> dict[str, Any]:
    actor = current.actor
    inc = incident_or_404(db, actor, incident_id)
    services = service_keys(db, actor.tenant_id)
    by_key = {s.key: s for s in services.values()}
    keys = list(dict.fromkeys([k for k in [services[inc.primary_service_id].key if inc.primary_service_id else None,
                                             *(inc.affected_services or [])] if k]))
    ids = [by_key[k].id for k in keys if k in by_key]
    deps = db.execute(select(ServiceDependency).where(or_(ServiceDependency.service_id.in_(ids),
                                                          ServiceDependency.depends_on_id.in_(ids)))).scalars().all()
    node_ids = set(ids) | {d.service_id for d in deps} | {d.depends_on_id for d in deps}
    timeline = db.execute(select(IncidentEvent).where(IncidentEvent.incident_id == inc.id)
                          .order_by(IncidentEvent.occurred_at)).scalars().all()
    logs = db.execute(select(LogEvent).where(LogEvent.service_id.in_(ids)).order_by(LogEvent.ts.desc()).limit(60)).scalars().all()
    allowed = [c.value for c, r in CLASSIFICATION_RANK.items() if r <= clearance_rank(actor.role)]
    related = db.execute(select(Incident).where(Incident.tenant_id == actor.tenant_id, Incident.id != inc.id,
                                                Incident.category == inc.category, Incident.classification.in_(allowed))
                         .order_by(Incident.detected_at.desc()).limit(6)).scalars().all()
    runs = db.execute(select(InvestigationRun).where(InvestigationRun.incident_id == inc.id,
                                                     InvestigationRun.is_evaluation.is_(False))
                      .order_by(InvestigationRun.created_at.desc()).limit(20)).scalars().all()
    users = UserCache(db)
    return {
        **incident_summary(inc, services),
        "description": inc.description, "impact": inc.impact, "customer_impact": inc.customer_impact,
        "attributes": inc.attributes, "resolution_criteria": inc.resolution_criteria,
        "resolution_summary": inc.resolution_summary, "tags": inc.tags,
        "timeline": [{"id": e.id, "occurred_at": e.occurred_at, "event_type": e.event_type, "source": e.source,
                      "summary": e.summary, "details": e.details} for e in timeline],
        "logs": [{"id": log_.id, "ts": log_.ts, "level": log_.level, "service": services[log_.service_id].key,
                  "message": neutralize(log_.message).text, "neutralized": neutralize(log_.message).detected}
                 for log_ in reversed(logs)],
        "dependency_map": {
            "nodes": [{"key": services[n].key, "name": services[n].name, "status": services[n].status,
                       "focus": n in ids} for n in node_ids if n in services],
            "edges": [{"from": services[d.service_id].key, "to": services[d.depends_on_id].key, "type": d.dependency_type}
                      for d in deps],
        },
        "related_incidents": [incident_summary(r, services) for r in related],
        "investigations": [run_out(db, r, users, include_state=False) for r in runs],
        "can_investigate": container.policy.can_read_classification(actor.role, inc.classification)
        and has_permission(actor.role, Permission.INVESTIGATIONS_START),
    }


@router.post("/incidents/{incident_id}/investigations", status_code=status.HTTP_202_ACCEPTED,
             summary="Start a bounded AI investigation (runs asynchronously)")
def start_investigation(incident_id: str, body: StartInvestigationRequest, db: DbDep, container: ContainerDep,
                        current: CurrentUser = Depends(require(Permission.INVESTIGATIONS_START))) -> dict[str, Any]:
    inc = incident_or_404(db, current.actor, incident_id)
    try:
        run = container.investigations.start(db, incident=inc, actor=current.actor, notes=body.notes)
    except InvestigationError as exc:
        raise ApiError(exc.http_status, exc.code, exc.message) from exc
    return run_out(db, run, UserCache(db), include_state=True, settings=container.settings)
