from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import ContainerDep, CurrentUser, DbDep, require
from app.api.pagination import PageParam, PageSizeParam, paginate
from app.core.errors import ApiError
from app.evaluation.harness import EvaluationError, EvaluationHarness
from app.models import EvaluationCaseResult, EvaluationRun
from app.policy.permissions import Permission
from app.schemas import EvaluationRunRequest

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


def eval_out(er: EvaluationRun) -> dict[str, Any]:
    return {"id": er.id, "status": er.status, "created_at": er.created_at, "completed_at": er.completed_at,
            "duration_ms": er.duration_ms, "dataset_id": er.dataset_id, "dataset_version": er.dataset_version,
            "provider": er.provider, "model": er.model, "model_mode": er.model_mode, "prompt_versions": er.prompt_versions,
            "retrieval_config": er.retrieval_config, "index_version": er.index_version,
            "workflow_version": er.workflow_version, "policy_version": er.policy_version, "bundle_hash": er.bundle_hash,
            "metrics": er.metrics, "thresholds": er.thresholds, "gate_passed": er.gate_passed,
            "gate_failures": er.gate_failures, "is_model_assisted": er.is_model_assisted,
            "judge_metrics": er.judge_metrics, "error_code": er.error_code,
            "measurement_note": "Measured by executing the pipeline on the synthetic dataset"
            + (" in MOCK MODE (deterministic mock provider - measures pipeline logic, not LLM quality)."
               if er.model_mode == "MOCK" else ".")}


@router.get("", summary="Evaluation runs (measured results)")
def list_evaluations(db: DbDep, page: PageParam = 1, page_size: PageSizeParam = 20,
                     current: CurrentUser = Depends(require(Permission.EVALUATIONS_READ))) -> dict[str, Any]:
    q = select(EvaluationRun).where(EvaluationRun.tenant_id == current.actor.tenant_id).order_by(EvaluationRun.created_at.desc())
    items, total = paginate(db, q, page, page_size)
    return {"items": [eval_out(e) for e in items], "total": total, "page": page, "page_size": page_size}


@router.post("/run", summary="Run the evaluation harness now (synchronous; dry-run workflows only)")
def run_evaluation(body: EvaluationRunRequest, db: DbDep, container: ContainerDep,
                   current: CurrentUser = Depends(require(Permission.EVALUATIONS_RUN))) -> dict[str, Any]:
    try:
        er = EvaluationHarness(container).run(db, current.actor, include_workflow=body.include_workflow)
    except EvaluationError as exc:
        raise ApiError(409, "evaluation_unavailable", str(exc)) from exc
    return eval_out(er)


@router.get("/{evaluation_id}", summary="Evaluation run detail with per-case results")
def get_evaluation(evaluation_id: str, db: DbDep,
                   current: CurrentUser = Depends(require(Permission.EVALUATIONS_READ))) -> dict[str, Any]:
    er = db.get(EvaluationRun, evaluation_id)
    if er is None or er.tenant_id != current.actor.tenant_id:
        raise ApiError(404, "not_found", "Evaluation run not found.")
    cases = db.execute(select(EvaluationCaseResult).where(EvaluationCaseResult.run_id == er.id)
                       .order_by(EvaluationCaseResult.case_type, EvaluationCaseResult.case_id)).scalars()
    return {**eval_out(er), "cases": [{"case_id": c.case_id, "case_type": c.case_type, "passed": c.passed,
                                       "metrics": c.metrics, "details": c.details} for c in cases]}
