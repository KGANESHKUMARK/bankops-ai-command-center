"""Approvals, idempotent simulated execution, state transitions, verification, rollback and audit."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import actor, incident
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db.base import utcnow
from app.models import ActionRecord, Approval, AuditEvent, InvestigationRun, LogEvent, Service
from app.services.approvals import ApprovalError
from app.services.audit import AuditImmutableError, verify_chain


def start(container, db, number="INC-1001", user="ops.analyst"):  # type: ignore[no-untyped-def]
    run = container.investigations.start(db, incident=incident(db, number), actor=actor(db, user), notes=None, sync=True)
    db.expire_all()
    return db.get(InvestigationRun, run.id)


def pending(db, run_id):  # type: ignore[no-untyped-def]
    return db.execute(select(Approval).where(Approval.investigation_id == run_id, Approval.status == "pending")
                      .order_by(Approval.created_at)).scalars().all()


def actions_of(db, run_id):  # type: ignore[no-untyped-def]
    db.expire_all()
    return db.execute(select(ActionRecord).where(ActionRecord.investigation_id == run_id)
                      .order_by(ActionRecord.step_index)).scalars().all()


def svc(db, key):  # type: ignore[no-untyped-def]
    db.expire_all()
    return db.execute(select(Service).where(Service.key == key, Service.tenant_id == "contoso-demo")).scalar_one()


def test_full_approval_execution_verification_and_idempotency(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(container, db)
    approval = pending(db, run.id)[0]
    with pytest.raises(ApprovalError) as exc:  # the analyst cannot approve
        container.approvals.decide(db, approval.id, actor(db, "ops.analyst"), "approve", reason_code="EVIDENCE_SUFFICIENT", comment=None)
    assert exc.value.code == "A-001" and exc.value.http_status == 403
    container.approvals.decide(db, approval.id, actor(db, "ops.manager"), "approve", reason_code="EVIDENCE_SUFFICIENT",
                               comment="Evidence reviewed")
    container.investigations.resume(db, db.get(InvestigationRun, run.id), actor(db, "ops.manager"), sync=True)
    db.expire_all()
    run = db.get(InvestigationRun, run.id)
    assert run.status == "completed" and run.outcome == "resolved"
    restart, reprocess = actions_of(db, run.id)
    assert restart.status == reprocess.status == "succeeded"
    assert restart.verification_status == reprocess.verification_status == "resolved"
    assert svc(db, "document-renderer").status == "healthy"
    assert incident(db, "INC-1001").status == "resolved"
    assert all(c["passed"] for c in reprocess.preconditions)

    logs_before = db.execute(select(LogEvent)).all()
    again = container.actions.execute(db, restart.id, actor=actor(db, "ops.manager"))
    assert again.status == "succeeded" and again.attempt_count == 1
    assert len(db.execute(select(LogEvent)).all()) == len(logs_before)
    with pytest.raises(ApprovalError) as exc:
        container.approvals.decide(db, approval.id, actor(db, "ops.manager2"), "approve", reason_code="EVIDENCE_SUFFICIENT", comment=None)
    assert exc.value.code == "A-003"


def test_pending_or_denied_actions_cannot_execute(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(container, db)
    restart = actions_of(db, run.id)[0]
    result = container.actions.execute(db, restart.id, actor=actor(db, "ops.manager"))
    assert result.status == "pending_approval" and result.executed_at is None
    assert svc(db, "document-renderer").status == "down"


def test_rejection_skips_dependent_step_and_is_audited(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(container, db)
    container.approvals.decide(db, pending(db, run.id)[0].id, actor(db, "ops.manager"), "reject", reason_code="RISK_TOO_HIGH",
                               comment="Not now")
    container.investigations.resume(db, db.get(InvestigationRun, run.id), actor(db, "ops.manager"), sync=True)
    restart, reprocess = actions_of(db, run.id)
    assert restart.status == "rejected" and reprocess.status == "skipped"
    assert reprocess.error_code.startswith("dependency_step_1")
    run = db.get(InvestigationRun, run.id)
    assert run.status == "completed" and run.outcome in ("no_action_taken", "insufficient_evidence")
    assert svc(db, "document-renderer").status == "down"
    actions = [e.action for e in db.execute(select(AuditEvent).where(AuditEvent.investigation_id == run.id)).scalars()]
    assert "approval.rejected" in actions and "action.skipped" in actions


def test_high_risk_separation_of_duties_end_to_end(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(container, db, number="INC-1003", user="ops.manager")
    approval = pending(db, run.id)[0]
    assert approval.risk_level == "high" and approval.required_roles == ["operations_manager"]
    for user in ("ops.manager", "demo.admin"):
        with pytest.raises(ApprovalError) as exc:
            container.approvals.decide(db, approval.id, actor(db, user), "approve", reason_code="EVIDENCE_SUFFICIENT", comment=None)
        assert exc.value.code in ("A-005", "A-002")
    container.approvals.decide(db, approval.id, actor(db, "ops.manager2"), "approve", reason_code="EVIDENCE_SUFFICIENT", comment=None)
    container.investigations.resume(db, db.get(InvestigationRun, run.id), actor(db, "ops.manager2"), sync=True)
    (flink,) = actions_of(db, run.id)
    assert flink.status == "succeeded" and svc(db, "flink-risk-aggregator").metrics["job_state"] == "RUNNING"
    assert svc(db, "schema-registry").metrics["subjects"]["risk-events-value"]["latest_version"] == 7


def test_database_blocks_self_approved_high_risk(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(container, db, number="INC-1003", user="ops.manager")
    approval = pending(db, run.id)[0]
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE approvals SET status='approved', decided_by=requested_by WHERE id=:id"), {"id": approval.id})
        db.commit()
    db.rollback()


def test_database_blocks_executable_prohibited_action(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(container, db)
    restart = actions_of(db, run.id)[0]
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE action_records SET risk_level='prohibited', status='approved' WHERE id=:id"), {"id": restart.id})
        db.commit()
    db.rollback()


def test_changed_plan_invalidates_approval(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(container, db)
    restart = actions_of(db, run.id)[0]
    restart.parameters = {**restart.parameters, "reason": "tampered after approval request"}
    db.commit()
    with pytest.raises(ApprovalError) as exc:
        container.approvals.decide(db, pending(db, run.id)[0].id, actor(db, "ops.manager"), "approve",
                                   reason_code="EVIDENCE_SUFFICIENT", comment=None)
    assert exc.value.code == "A-006"


def test_new_investigation_supersedes_old_pending_approvals(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    first = start(container, db)
    old = pending(db, first.id)[0]
    second = start(container, db, user="ops.analyst2")
    db.expire_all()
    assert db.get(Approval, old.id).status == "invalidated"
    assert db.get(InvestigationRun, first.id).status == "cancelled"
    assert pending(db, second.id)


def test_expired_approval_cannot_be_approved(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(container, db)
    approval = pending(db, run.id)[0]
    approval.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    with pytest.raises(ApprovalError) as exc:
        container.approvals.decide(db, approval.id, actor(db, "ops.manager"), "approve", reason_code="EVIDENCE_SUFFICIENT", comment=None)
    assert exc.value.code in ("A-003", "A-004")
    db.expire_all()
    assert db.get(Approval, approval.id).status == "expired" and actions_of(db, run.id)[0].status == "expired"


def test_resume_refused_while_approvals_pending(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    from app.services.investigations import InvestigationError

    run = start(container, db)
    with pytest.raises(InvestigationError) as exc:
        container.investigations.resume(db, run, actor(db, "ops.analyst"), sync=True)
    assert exc.value.code == "approvals_pending"


def test_interrupted_execution_is_not_retried(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    run = start(container, db)
    container.approvals.decide(db, pending(db, run.id)[0].id, actor(db, "ops.manager"), "approve", reason_code="EVIDENCE_SUFFICIENT", comment=None)
    restart = actions_of(db, run.id)[0]
    restart.status = "executing"  # simulate a crash between claim and completion
    db.commit()
    container.investigations.resume(db, db.get(InvestigationRun, run.id), actor(db, "ops.manager"), sync=True)
    restart, reprocess = actions_of(db, run.id)
    assert restart.status == "failed" and restart.error_code == "interrupted_during_execution"
    assert reprocess.status == "skipped" and svc(db, "document-renderer").status == "down"


def test_rollback_supported_and_unsupported(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    from app.services.actions import ActionError

    run = start(container, db, number="INC-1002")
    scale_approval, replay_approval = pending(db, run.id)
    container.approvals.decide(db, scale_approval.id, actor(db, "ops.manager"), "approve", reason_code="EVIDENCE_SUFFICIENT", comment=None)
    container.approvals.decide(db, replay_approval.id, actor(db, "ops.manager"), "reject", reason_code="RISK_TOO_HIGH", comment=None)
    container.investigations.resume(db, db.get(InvestigationRun, run.id), actor(db, "ops.manager"), sync=True)
    scale, replay = actions_of(db, run.id)
    assert scale.status == "succeeded" and replay.status == "rejected" and replay.executed_at is None
    assert svc(db, "transaction-enricher").metrics["replicas"] == 6
    assert db.get(InvestigationRun, run.id).outcome == "resolved"
    rolled = container.actions.rollback(db, scale, actor=actor(db, "ops.manager"), reason="test rollback")
    assert rolled.status == "rolled_back" and svc(db, "transaction-enricher").metrics["replicas"] == 3
    assert incident(db, "INC-1002").status == "investigating"
    with pytest.raises(ActionError):
        container.actions.rollback(db, rolled, actor=actor(db, "ops.manager"), reason="again")

    run_a = start(container, db)
    container.approvals.decide(db, pending(db, run_a.id)[0].id, actor(db, "ops.manager"), "approve", reason_code="EVIDENCE_SUFFICIENT", comment=None)
    container.investigations.resume(db, db.get(InvestigationRun, run_a.id), actor(db, "ops.manager"), sync=True)
    restart = actions_of(db, run_a.id)[0]
    with pytest.raises(ActionError) as exc:
        container.actions.rollback(db, restart, actor=actor(db, "ops.manager"), reason="try")
    assert exc.value.code == "rollback_not_supported"


def test_audit_log_is_append_only_and_hash_chained(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    start(container, db)
    assert verify_chain(db, "contoso-demo")["valid"] is True
    ev = db.execute(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1)).scalar_one()
    ev.outcome = "denied"
    with pytest.raises(AuditImmutableError):
        db.flush()
    db.rollback()
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("UPDATE audit_events SET outcome='denied' WHERE id=:id"), {"id": ev.id})
    db.rollback()
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("DELETE FROM audit_events WHERE id=:id"), {"id": ev.id})
    db.rollback()
