"""Composition root: wires services once per process (dependency injection)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from app.agents.runner import WorkflowRunner
from app.agents.tools import ToolExecutor
from app.agents.workflow import InvestigationWorkflow
from app.ai.gateway import LLMProvider, ModelGateway, build_provider
from app.core.config import Settings
from app.db.session import get_session_factory
from app.policy.engine import PolicyEngine
from app.rag.embeddings import Embedder, get_embedder
from app.rag.ingestion import IngestionService
from app.rag.retrieval import Retriever
from app.services.actions import ActionService
from app.services.approvals import ApprovalService
from app.services.investigations import InvestigationService
from app.services.metrics import RequestMetrics


@dataclass
class Container:
    settings: Settings
    session_factory: sessionmaker[Session]
    policy: PolicyEngine
    embedder: Embedder
    retriever: Retriever
    ingestion: IngestionService
    gateway: ModelGateway
    tools: ToolExecutor
    actions: ActionService
    approvals: ApprovalService
    workflow: InvestigationWorkflow
    runner: WorkflowRunner
    investigations: InvestigationService
    metrics: RequestMetrics

    def shutdown(self) -> None:
        self.runner.shutdown(wait=True)


def build_container(settings: Settings, *, provider: LLMProvider | None = None,
                    session_factory: sessionmaker[Session] | None = None) -> Container:
    session_factory = session_factory or get_session_factory()
    policy = PolicyEngine(settings)
    embedder = get_embedder(settings)
    retriever = Retriever(settings, embedder)
    gateway = ModelGateway(settings, provider or build_provider(settings))
    tools = ToolExecutor(settings, policy)
    actions = ActionService(settings, policy, tools)
    approvals = ApprovalService(settings, policy)
    workflow = InvestigationWorkflow(settings=settings, gateway=gateway, retriever=retriever, tools=tools,
                                     actions=actions, approvals=approvals, policy=policy)
    runner = WorkflowRunner(settings, session_factory, workflow)
    return Container(
        settings=settings, session_factory=session_factory, policy=policy, embedder=embedder, retriever=retriever,
        ingestion=IngestionService(settings, embedder), gateway=gateway, tools=tools, actions=actions,
        approvals=approvals, workflow=workflow, runner=runner,
        investigations=InvestigationService(settings, runner, gateway), metrics=RequestMetrics(),
    )
