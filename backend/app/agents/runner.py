"""In-process bounded worker pool for investigations.

A run is claimed with an atomic compare-and-set (queued -> running) so two workers
can never execute the same run. Context variables (request/correlation IDs) are
propagated into worker threads. Production deployments would replace this with a
durable queue (see docs/DECISIONS.md); Vercel is not used for the backend.
"""

from __future__ import annotations

import contextvars
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, update
from sqlalchemy.orm import Session, sessionmaker

from app.agents.workflow import InvestigationWorkflow
from app.core.config import Settings
from app.core.logging import get_logger
from app.db.base import utcnow
from app.domain import InvestigationStatus
from app.models import InvestigationRun, User
from app.policy.engine import Actor

log = get_logger("agents.runner")


class WorkflowRunner:
    def __init__(self, settings: Settings, session_factory: sessionmaker[Session], workflow: InvestigationWorkflow) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.workflow = workflow
        self._executor: ThreadPoolExecutor | None = None
        if settings.workflow_execution_mode == "background":
            self._executor = ThreadPoolExecutor(max_workers=settings.workflow_worker_threads,
                                                thread_name_prefix="investigation")

    def submit(self, run_id: str, *, sync: bool = False) -> None:
        if sync or self._executor is None:
            self._execute(run_id)
            return
        ctx = contextvars.copy_context()
        self._executor.submit(ctx.run, self._execute_safe, run_id)

    def _execute_safe(self, run_id: str) -> None:
        try:
            self._execute(run_id)
        except Exception:
            log.exception("investigation worker crashed", extra={"investigation_id": run_id})
            with self.session_factory() as db:
                db.execute(update(InvestigationRun).where(InvestigationRun.id == run_id,
                                                          InvestigationRun.status == InvestigationStatus.RUNNING.value)
                           .values(status=InvestigationStatus.INTERRUPTED.value, error_code="worker_crash"))
                db.commit()

    def _execute(self, run_id: str) -> None:
        with self.session_factory() as db:
            res = db.execute(
                update(InvestigationRun)
                .where(InvestigationRun.id == run_id, InvestigationRun.status == InvestigationStatus.QUEUED.value)
                .values(status=InvestigationStatus.RUNNING.value, lock_token=str(uuid.uuid4()),
                        started_at=func.coalesce(InvestigationRun.started_at, utcnow()), updated_at=utcnow())
            )
            db.commit()
            if res.rowcount != 1:  # type: ignore[attr-defined]
                log.info("run not claimable (already claimed or not queued)", extra={"investigation_id": run_id})
                return
            run = db.get(InvestigationRun, run_id)
            assert run is not None
            user = db.get(User, run.requested_by)
            assert user is not None
            actor = Actor(user_id=user.id, username=user.username, role=user.role, tenant_id=user.tenant_id)
            self.workflow.run(db, run, actor)

    def shutdown(self, *, wait: bool = True) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=wait, cancel_futures=True)
