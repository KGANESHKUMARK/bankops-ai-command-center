from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.agents.workflow import AGENTS, WORKFLOW_VERSION
from app.ai.prompts import PROMPTS
from app.api.deps import ContainerDep, CurrentUser, DbDep, require
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.core.errors import ApiError
from app.domain import CLASSIFICATION_RANK, ROLE_CLEARANCE, Role
from app.evaluation.harness import bundle_components, bundle_hash, load_dataset, load_thresholds
from app.models import AuditEvent, ModelConfigVersion, PolicyDecisionRecord, PromptVersion, ReleasePromotion, User
from app.policy.catalog import ACTION_CATALOG, PROHIBITED_ACTIONS
from app.policy.engine import POLICY_RULES, POLICY_VERSION
from app.policy.permissions import ROLE_DESCRIPTIONS, ROLE_PERMISSIONS, Permission
from app.rag.injection import PATTERN_CATALOG
from app.schemas import PromotionRequest, PromotionRollbackRequest, RetentionApplyRequest
from app.services import promotions
from app.services.audit import verify_chain
from app.services.retention import apply_retention, retention_report

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/audit", summary="Append-only audit log (paginated, filterable)")
def audit_log(
    db: DbDep,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    action: Annotated[str | None, Query(max_length=80, pattern=r"^[a-z_.]+$")] = None,
    outcome: Annotated[str | None, Query(pattern=r"^(success|denied|failure|info)$")] = None,
    investigation_id: Annotated[str | None, Query(max_length=36)] = None,
    current: CurrentUser = Depends(require(Permission.AUDIT_READ)),
) -> dict[str, Any]:
    q = select(AuditEvent).where(AuditEvent.tenant_id == current.actor.tenant_id)
    if action:
        q = q.where(AuditEvent.action.like(f"{action}%"))
    if outcome:
        q = q.where(AuditEvent.outcome == outcome)
    if investigation_id:
        q = q.where(AuditEvent.investigation_id == investigation_id)
    items, total = paginate(db, q.order_by(AuditEvent.id.desc()), page, page_size)
    return {"items": [{"id": e.id, "event_id": e.event_id, "occurred_at": e.occurred_at, "actor": e.actor_username,
                       "actor_role": e.actor_role, "action": e.action, "resource_type": e.resource_type,
                       "resource_id": e.resource_id, "outcome": e.outcome, "request_id": e.request_id,
                       "investigation_id": e.investigation_id, "details": e.details, "hash": e.hash,
                       "prev_hash": e.prev_hash} for e in items],
            "total": total, "page": page, "page_size": page_size}


@router.get("/audit/verify", summary="Verify the tenant's audit hash chain (tamper evidence)")
def audit_verify(db: DbDep, current: CurrentUser = Depends(require(Permission.AUDIT_READ))) -> dict[str, Any]:
    return verify_chain(db, current.actor.tenant_id)


@router.get("/policies", summary="Deterministic policy rules, RBAC matrix, action risk catalog and data classes")
def policies(container: ContainerDep, current: CurrentUser = Depends(require(Permission.GOVERNANCE_READ))) -> dict[str, Any]:
    s = container.settings
    return {
        "policy_version": POLICY_VERSION,
        "rules": [{"id": k, "description": v} for k, v in POLICY_RULES.items()],
        "roles": [{"role": r.value, "description": ROLE_DESCRIPTIONS[r], "clearance": ROLE_CLEARANCE[r].value,
                   "permissions": sorted(p.value for p in ROLE_PERMISSIONS[r])} for r in Role],
        "permissions": [p.value for p in Permission],
        "action_catalog": [{"tool": p.tool_name, "risk_level": p.risk.value, "description": p.description,
                            "allowed_targets": list(p.allowed_targets), "approver_roles": [r.value for r in p.approver_roles],
                            "rollback_supported": p.rollback_supported, "rollback_note": p.rollback_note}
                           for p in ACTION_CATALOG.values()],
        "prohibited_actions": [{"tool": k, "reason": v} for k, v in PROHIBITED_ACTIONS.items()],
        "configuration": {"medium_risk_requires_approval": s.medium_risk_requires_approval,
                          "low_risk_requires_approval": s.low_risk_requires_approval,
                          "allow_self_approval_medium": s.allow_self_approval_medium,
                          "approval_ttl_minutes": s.approval_ttl_minutes},
        "injection_patterns": PATTERN_CATALOG,
    }


@router.get("/classifications", summary="Data classification labels and role clearances")
def classifications(current: CurrentUser = Depends(require(Permission.GOVERNANCE_READ))) -> dict[str, Any]:
    return {"levels": [{"classification": c.value, "rank": r,
                        "roles_with_clearance": [role.value for role, cl in ROLE_CLEARANCE.items()
                                                 if CLASSIFICATION_RANK[cl] >= r]}
                       for c, r in CLASSIFICATION_RANK.items()],
            "note": "All content is fictional. Clearance and per-document allowed roles are enforced in SQL and "
                    "re-checked in application code before any content reaches a user or model."}


@router.get("/policy-decisions", summary="Recorded deterministic policy decisions (paginated)")
def policy_decisions(
    db: DbDep,
    page: PageParam = 1,
    page_size: PageSizeParam = 50,
    decision: Annotated[str | None, Query(pattern=r"^(allow|deny|require_approval)$")] = None,
    current: CurrentUser = Depends(require(Permission.GOVERNANCE_READ)),
) -> dict[str, Any]:
    q = select(PolicyDecisionRecord).where(PolicyDecisionRecord.tenant_id == current.actor.tenant_id)
    if decision:
        q = q.where(PolicyDecisionRecord.decision == decision)
    items, total = paginate(db, q.order_by(PolicyDecisionRecord.created_at.desc()), page, page_size)
    return {"items": [{"id": d.id, "created_at": d.created_at, "investigation_id": d.investigation_id,
                       "action_id": d.action_id, "subject_role": d.subject_role, "action_name": d.action_name,
                       "resource": d.resource, "risk_level": d.risk_level, "decision": d.decision,
                       "rule_ids": d.rule_ids, "explanation": d.explanation, "policy_version": d.policy_version}
                      for d in items], "total": total, "page": page, "page_size": page_size}


@router.get("/model-versions", summary="Prompt, model, embedding, index, workflow and dataset versions")
def model_versions(db: DbDep, container: ContainerDep,
                   current: CurrentUser = Depends(require(Permission.GOVERNANCE_READ))) -> dict[str, Any]:
    components = bundle_components(container)
    registered = {(p.prompt_id, p.version): p for p in db.execute(select(PromptVersion)).scalars()}
    return {
        "active_bundle": {"hash": bundle_hash(components), "components": components},
        "prompts": [{"prompt_id": p.prompt_id, "version": p.version, "description": p.description,
                     "template_hash": p.template_hash, "registered": (p.prompt_id, p.version) in registered}
                    for p in PROMPTS.values()],
        "model_configs": [{"id": m.id, "provider": m.provider, "model": m.model, "embedding_provider": m.embedding_provider,
                           "embedding_model": m.embedding_model, "embedding_dim": m.embedding_dim,
                           "config_hash": m.config_hash, "created_at": m.created_at}
                          for m in db.execute(select(ModelConfigVersion).order_by(ModelConfigVersion.created_at.desc())).scalars()],
        "gateway": container.gateway.status(),
        "workflow": {"version": WORKFLOW_VERSION, "agents": AGENTS},
        "dataset": {k: load_dataset()[k] for k in ("dataset_id", "version", "description")},
        "thresholds_version": load_thresholds()["version"],
    }


@router.get("/users", summary="Users and roles in the caller's tenant (no credentials)")
def users(db: DbDep, current: CurrentUser = Depends(require(Permission.USERS_READ))) -> list[dict[str, Any]]:
    rows = db.execute(select(User).where(User.tenant_id == current.actor.tenant_id).order_by(User.username)).scalars()
    return [{"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role,
             "is_active": u.is_active, "is_demo_account": u.is_demo_account, "last_login_at": u.last_login_at}
            for u in rows]


@router.get("/promotions", summary="Simulated environment promotions of AI configuration bundles")
def list_promotions(db: DbDep, container: ContainerDep,
                    current: CurrentUser = Depends(require(Permission.GOVERNANCE_READ))) -> dict[str, Any]:
    rows = db.execute(select(ReleasePromotion).where(ReleasePromotion.tenant_id == current.actor.tenant_id)
                      .order_by(ReleasePromotion.created_at.desc()).limit(100)).scalars().all()
    active = promotions.active_by_env(db, current.actor.tenant_id)
    return {"environments": {env: (promotions.promotion_out(p) if p else None) for env, p in active.items()},
            "history": [promotions.promotion_out(p) for p in rows],
            "current_bundle_hash": bundle_hash(bundle_components(container)),
            "note": "SIMULATED promotion workflow - no real deployment or production release occurs."}


@router.post("/promotions", summary="Promote the current bundle (requires a passing evaluation of the same bundle)")
def create_promotion(body: PromotionRequest, db: DbDep, container: ContainerDep,
                     current: CurrentUser = Depends(require(Permission.PROMOTIONS_MANAGE))) -> dict[str, Any]:
    try:
        rec = promotions.promote(db, container, current.actor, to_env=body.to_env,
                                 evaluation_run_id=body.evaluation_run_id, notes=body.notes)
    except promotions.PromotionError as exc:
        raise ApiError(exc.http_status, exc.code, exc.message) from exc
    return promotions.promotion_out(rec)


@router.post("/promotions/{promotion_id}/rollback", summary="Roll back an environment to its previous bundle")
def rollback_promotion(promotion_id: str, body: PromotionRollbackRequest, db: DbDep,
                       current: CurrentUser = Depends(require(Permission.PROMOTIONS_MANAGE))) -> dict[str, Any]:
    try:
        rec = promotions.rollback(db, current.actor, promotion_id, body.reason)
    except promotions.PromotionError as exc:
        raise ApiError(exc.http_status, exc.code, exc.message) from exc
    return promotions.promotion_out(rec)


@router.get("/retention", summary="Retention policy and purge candidates")
def retention(db: DbDep, container: ContainerDep,
              current: CurrentUser = Depends(require(Permission.GOVERNANCE_READ))) -> dict[str, Any]:
    return retention_report(db, container.settings, current.actor.tenant_id)


@router.post("/retention/apply", summary="Apply retention (dry-run by default)")
def retention_apply(body: RetentionApplyRequest, db: DbDep, container: ContainerDep,
                    current: CurrentUser = Depends(require(Permission.RETENTION_MANAGE))) -> dict[str, Any]:
    return apply_retention(db, container.settings, current.actor, dry_run=body.dry_run)
