"""Simulated promotion of a versioned AI configuration bundle: development -> staging -> production_ready.

No real deployment happens. Promotion requires a completed evaluation run of the
*same* bundle that passed the required release thresholds, and each stage must
follow the previous one. Rollback restores the previously active bundle record.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluation.harness import bundle_components, bundle_hash
from app.models import EvaluationRun, ReleasePromotion
from app.policy.engine import Actor
from app.services.audit import record_audit
from app.services.container import Container

ENVIRONMENTS = ["development", "staging", "production_ready"]


class PromotionError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def active_by_env(db: Session, tenant_id: str) -> dict[str, ReleasePromotion | None]:
    rows = db.execute(select(ReleasePromotion).where(ReleasePromotion.tenant_id == tenant_id)
                      .order_by(ReleasePromotion.created_at)).scalars().all()
    rolled_back = {r.rollback_of_id for r in rows if r.status == "rolled_back" and r.rollback_of_id}
    active: dict[str, ReleasePromotion | None] = dict.fromkeys(ENVIRONMENTS)
    stack: dict[str, list[ReleasePromotion]] = {env: [] for env in ENVIRONMENTS}
    for r in rows:
        if r.status == "promoted" and r.id not in rolled_back:
            stack[r.to_env].append(r)
        elif r.status == "rolled_back" and r.rollback_of_id:
            stack[r.to_env] = [p for p in stack[r.to_env] if p.id != r.rollback_of_id]
    for env in ENVIRONMENTS:
        active[env] = stack[env][-1] if stack[env] else None
    return active


def promote(db: Session, container: Container, actor: Actor, *, to_env: str, evaluation_run_id: str,
            notes: str | None) -> ReleasePromotion:
    er = db.get(EvaluationRun, evaluation_run_id)
    if er is None or er.tenant_id != actor.tenant_id:
        raise PromotionError("not_found", "Evaluation run not found.", 404)
    components = bundle_components(container)
    current_hash = bundle_hash(components)
    active = active_by_env(db, actor.tenant_id)
    idx = ENVIRONMENTS.index(to_env)
    failures: list[str] = []
    if er.status != "completed":
        failures.append(f"Evaluation run is {er.status}.")
    if er.bundle_hash != current_hash:
        failures.append("Evaluation was run against a different configuration bundle; re-run the evaluation.")
    if not er.gate_passed:
        failures.extend(er.gate_failures or ["Release gate did not pass."])
    if idx > 0:
        prev_env = ENVIRONMENTS[idx - 1]
        prev = active[prev_env]
        if prev is None or prev.bundle_hash != current_hash:
            failures.append(f"Bundle must be active in {prev_env} before promotion to {to_env}.")
    currently_active = active[to_env]
    rec = ReleasePromotion(
        tenant_id=actor.tenant_id, bundle_hash=current_hash, components=components,
        from_env=ENVIRONMENTS[idx - 1] if idx > 0 else None, to_env=to_env,
        status="blocked" if failures else "promoted", evaluation_run_id=er.id, gate_passed=not failures,
        gate_failures=failures, promoted_by=actor.user_id,
        previous_promotion_id=currently_active.id if currently_active is not None else None,
        notes=(notes or "")[:500] or None,
    )
    db.add(rec)
    db.flush()
    record_audit(db, tenant_id=actor.tenant_id, action=f"promotion.{rec.status}", resource_type="release_promotion",
                 resource_id=rec.id, actor=actor, outcome="success" if not failures else "denied",
                 details={"to_env": to_env, "bundle_hash": current_hash[:16], "failures": failures[:10],
                          "simulated": True})
    db.commit()
    return rec


def rollback(db: Session, actor: Actor, promotion_id: str, reason: str) -> ReleasePromotion:
    target = db.get(ReleasePromotion, promotion_id)
    if target is None or target.tenant_id != actor.tenant_id:
        raise PromotionError("not_found", "Promotion not found.", 404)
    active = active_by_env(db, actor.tenant_id)
    if active[target.to_env] is None or active[target.to_env].id != target.id:  # type: ignore[union-attr]
        raise PromotionError("not_active", "Only the currently active promotion of an environment can be rolled back.")
    rec = ReleasePromotion(
        tenant_id=actor.tenant_id, bundle_hash=target.bundle_hash, components=target.components,
        from_env=target.to_env, to_env=target.to_env, status="rolled_back", evaluation_run_id=target.evaluation_run_id,
        gate_passed=target.gate_passed, gate_failures=[], promoted_by=actor.user_id,
        previous_promotion_id=target.previous_promotion_id, rollback_of_id=target.id, notes=reason[:500],
    )
    db.add(rec)
    db.flush()
    record_audit(db, tenant_id=actor.tenant_id, action="promotion.rolled_back", resource_type="release_promotion",
                 resource_id=rec.id, actor=actor,
                 details={"env": target.to_env, "rolled_back": target.id, "restored": target.previous_promotion_id,
                          "reason": reason[:300], "simulated": True})
    db.commit()
    return rec


def promotion_out(p: ReleasePromotion) -> dict[str, Any]:
    return {"id": p.id, "bundle_hash": p.bundle_hash, "components": p.components, "from_env": p.from_env,
            "to_env": p.to_env, "status": p.status, "evaluation_run_id": p.evaluation_run_id,
            "gate_passed": p.gate_passed, "gate_failures": p.gate_failures, "promoted_by": p.promoted_by,
            "previous_promotion_id": p.previous_promotion_id, "rollback_of_id": p.rollback_of_id, "notes": p.notes,
            "created_at": p.created_at, "simulated": True}
