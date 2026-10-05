"""Evaluation harness metrics, release gate, promotion workflow, retention."""

from __future__ import annotations

import pytest
from conftest import actor
from sqlalchemy import delete, select

from app.evaluation.harness import EvaluationHarness
from app.evaluation.metrics import f1, precision_at_k, recall_at_k, reciprocal_rank
from app.models import EvaluationCaseResult, EvaluationRun, ReleasePromotion
from app.services import promotions
from app.services.promotions import PromotionError


@pytest.fixture(autouse=True)
def _no_leaked_promotions(db):  # type: ignore[no-untyped-def]
    """Evaluation/promotion history is governance data, not demo state, so `clean` does not reset it.
    Clear it here so each promotion test starts from a known empty state."""
    db.execute(delete(ReleasePromotion))
    db.execute(delete(EvaluationCaseResult))
    db.execute(delete(EvaluationRun))
    db.commit()


def test_retrieval_metric_functions() -> None:
    assert recall_at_k(["a", "b", "c"], {"a"}, 3) == 1.0
    assert recall_at_k(["x"], {"a"}, 1) == 0.0
    assert precision_at_k(["a", "x"], {"a", "b"}, 2) == 0.5
    assert reciprocal_rank(["x", "y", "a"], {"a"}) == 1 / 3
    assert reciprocal_rank(["x"], {"a"}) == 0.0
    assert f1(1.0, 0.0) == 0.0 and round(f1(1.0, 1.0), 4) == 1.0


def test_full_evaluation_passes_gate_and_is_measured(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = EvaluationHarness(container).run(db, actor(db, "ops.manager"), include_workflow=True)
    db.expire_all()
    run = db.get(EvaluationRun, run.id)
    assert run.status == "completed" and run.dataset_id == "bankops-eval" and run.dataset_version == "1.0.0"
    m = run.metrics
    assert m["retrieval.cases"] == 16 and m["injection.cases"] == 4 and m["workflow.cases"] == 10
    assert run.gate_passed is True and run.gate_failures == []
    assert m["retrieval.unauthorized_leaks"] == 0 and m["safety.prohibited_action_executions"] == 0
    assert m["injection.resistance"] == 1.0 and m["safety.policy_compliance"] == 1.0
    assert run.model_mode == "MOCK" and run.is_model_assisted is False


def test_promotion_blocked_by_failed_gate(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    mgr = actor(db, "ops.manager")
    run = EvaluationHarness(container).run(db, mgr, include_workflow=True)
    run.gate_passed = False  # simulate a failed gate
    db.commit()
    rec = promotions.promote(db, container, mgr, to_env="development", evaluation_run_id=run.id, notes=None)
    assert rec.status == "blocked" and rec.gate_failures


def test_promotion_full_pipeline_with_rollback(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    mgr = actor(db, "ops.manager")
    run = EvaluationHarness(container).run(db, mgr, include_workflow=True)
    dev = promotions.promote(db, container, mgr, to_env="development", evaluation_run_id=run.id, notes="dev")
    assert dev.status == "promoted" and dev.from_env is None
    staging = promotions.promote(db, container, mgr, to_env="staging", evaluation_run_id=run.id, notes="stage it")
    assert staging.status == "promoted" and staging.from_env == "development"
    prod = promotions.promote(db, container, mgr, to_env="production_ready", evaluation_run_id=run.id, notes=None)
    assert prod.status == "promoted" and prod.from_env == "staging"
    rolled = promotions.rollback(db, mgr, promotion_id=prod.id, reason="regression found")
    assert rolled.status == "rolled_back"
    active = promotions.active_by_env(db, mgr.tenant_id)
    assert active["production_ready"] is None and active["staging"].id == staging.id


def test_promotion_requires_previous_stage_and_valid_run(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    mgr = actor(db, "ops.manager")
    run = EvaluationHarness(container).run(db, mgr, include_workflow=True)
    skip = promotions.promote(db, container, mgr, to_env="staging", evaluation_run_id=run.id, notes=None)
    assert skip.status == "blocked"  # cannot skip "development"
    try:
        promotions.promote(db, container, mgr, to_env="development", evaluation_run_id="does-not-exist", notes=None)
        raise AssertionError("expected PromotionError")
    except PromotionError as exc:
        assert exc.code == "not_found"


def test_rollback_requires_active_promotion(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    mgr = actor(db, "ops.manager")
    run = EvaluationHarness(container).run(db, mgr, include_workflow=True)
    dev = promotions.promote(db, container, mgr, to_env="development", evaluation_run_id=run.id, notes=None)
    promotions.rollback(db, mgr, promotion_id=dev.id, reason="undo")
    try:
        promotions.rollback(db, mgr, promotion_id=dev.id, reason="again")
        raise AssertionError("expected PromotionError")
    except PromotionError as exc:
        assert exc.code == "not_active"


def test_evaluation_results_rows_recorded(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = EvaluationHarness(container).run(db, actor(db, "ops.manager"), include_workflow=True)
    db.expire_all()
    cases = db.execute(select(EvaluationCaseResult).where(EvaluationCaseResult.run_id == run.id)).scalars().all()
    assert len(cases) >= 16 and all(c.passed is not None for c in cases)


def test_re_running_evaluation_against_changed_bundle_blocks_promotion(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    mgr = actor(db, "ops.manager")
    run = EvaluationHarness(container).run(db, mgr, include_workflow=True)
    run.bundle_hash = "tampered" * 8
    db.commit()
    rec = promotions.promote(db, container, mgr, to_env="development", evaluation_run_id=run.id, notes=None)
    assert rec.status == "blocked"
    assert any("different configuration bundle" in f for f in rec.gate_failures)
