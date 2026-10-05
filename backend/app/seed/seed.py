"""Deterministic, idempotent seeding and demo reset.

Seed records use deterministic UUIDv5 IDs; running the seeder repeatedly creates
nothing new. `reset_demo` restores the synthetic baseline (operational data,
service state, incidents and knowledge) while preserving the append-only audit log
and evaluation history.
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.prompts import PROMPTS
from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.base import seed_id, utcnow
from app.domain import Classification
from app.models import (
    ActionRecord,
    Approval,
    DemoFlag,
    Evidence,
    Incident,
    IncidentEvent,
    InvestigationEvent,
    InvestigationRun,
    KnowledgeChunk,
    KnowledgeDocument,
    LLMCall,
    LogEvent,
    ModelConfigVersion,
    PolicyDecisionRecord,
    PromptVersion,
    RetrievalLog,
    Service,
    ServiceDependency,
    Tenant,
    ToolCall,
    User,
)
from app.policy.engine import Actor, canonical_json
from app.rag.ingestion import IngestRequest
from app.rag.pdf import build_text_pdf
from app.seed import data
from app.services.audit import record_audit
from app.services.container import Container

log = get_logger("seed")
KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
DEMO_TENANTS = [t[0] for t in data.TENANTS]


class SeedError(RuntimeError):
    pass


def register_versions(db: Session, container: Container) -> None:
    """Record prompt and model configuration versions (idempotent) for governance."""
    existing = {(p.prompt_id, p.version) for p in db.execute(select(PromptVersion)).scalars()}
    for p in PROMPTS.values():
        if (p.prompt_id, p.version) not in existing:
            db.add(PromptVersion(prompt_id=p.prompt_id, version=p.version, template_hash=p.template_hash,
                                 description=p.description[:300]))
    s = container.settings
    params = {"temperature": 0, "max_output_tokens": s.llm_max_output_tokens, "timeout_seconds": s.llm_timeout_seconds,
              "max_retries": s.llm_max_retries}
    cfg = {"provider": container.gateway.provider.name, "model": container.gateway.provider.model,
           "embedding_provider": s.embedding_provider, "embedding_model": container.embedder.model,
           "embedding_dim": s.embedding_dim, "parameters": params}
    config_hash = hashlib.sha256(canonical_json(cfg).encode()).hexdigest()
    if db.execute(select(ModelConfigVersion).where(ModelConfigVersion.config_hash == config_hash)).first() is None:
        db.add(ModelConfigVersion(config_hash=config_hash, **cfg))
    db.commit()


def _seed_identity(db: Session, container: Container) -> int:
    created = 0
    for tid, name in data.TENANTS:
        if db.get(Tenant, tid) is None:
            db.add(Tenant(id=tid, name=name, is_synthetic=True))
    db.flush()
    password = container.settings.demo_password
    if password is None or not password.get_secret_value():
        raise SeedError("DEMO_PASSWORD is not set. Copy .env.example to .env (local/demo only) before seeding.")
    if container.settings.is_production_like:
        raise SeedError("Demo accounts cannot be seeded in staging/production.")
    for tid, username, display, role in data.USERS:
        uid = seed_id("user", username)
        if db.get(User, uid) is None:
            db.add(User(id=uid, tenant_id=tid, username=username, display_name=display,
                        email=f"{username}@{tid.split('-')[0]}.example", password_hash=hash_password(password.get_secret_value()),
                        role=role, is_active=True, is_demo_account=True))
            created += 1
    db.flush()
    return created


def _seed_services(db: Session) -> None:
    for tid, services in data.SERVICES.items():
        for key, name, tier, owner, status, metrics in services:
            sid = seed_id("service", tid, key)
            if db.get(Service, sid) is None:
                db.add(Service(id=sid, tenant_id=tid, key=key, name=name, description=f"{name} (synthetic)",
                               tier=tier, owner_team=owner, status=status, metrics=copy.deepcopy(metrics)))
        db.flush()
        for svc, dep, kind in data.DEPENDENCIES[tid]:
            did = seed_id("dependency", tid, svc, dep)
            if db.get(ServiceDependency, did) is None:
                db.add(ServiceDependency(id=did, tenant_id=tid, service_id=seed_id("service", tid, svc),
                                         depends_on_id=seed_id("service", tid, dep), dependency_type=kind))
    db.flush()


def _seed_incidents(db: Session) -> int:
    created = 0
    owners = {"contoso-demo": seed_id("user", "ops.manager"), "fabrikam-demo": seed_id("user", "fab.manager")}
    for tid, incidents in data.INCIDENTS.items():
        all_inc = incidents + (data.background_incidents() if tid == data.CONTOSO else [])
        for spec in all_inc:
            iid = seed_id("incident", tid, spec["number"])
            if db.get(Incident, iid) is not None:
                continue
            created += 1
            resolved = spec.get("resolved")
            db.add(Incident(
                id=iid, tenant_id=tid, number=spec["number"], title=spec["title"], description=spec["description"],
                category=spec["category"], severity=spec["severity"], status=spec["status"],
                classification=spec["classification"], primary_service_id=seed_id("service", tid, spec["primary"]),
                affected_services=spec["affected"], owner_team=spec["owner"], owner_user_id=owners[tid],
                impact=spec["impact"], customer_impact=spec["customer_impact"], detected_at=spec["detected"],
                updated_at=resolved or spec["detected"], resolved_at=resolved, scenario_key=spec["scenario_key"],
                resolution_criteria=spec["criteria"], attributes=spec["attributes"],
                resolution_summary=spec["resolution_summary"], tags=spec["tags"], is_synthetic=True,
            ))
            db.flush()
            timeline = spec["timeline"] or ([(spec["detected"], "status_change", "incident-manager", "Incident opened")]
                                            + ([(resolved, "status_change", "incident-manager", "Resolved")] if resolved else []))
            for n, (ts, etype, source, summary) in enumerate(timeline):
                db.add(IncidentEvent(id=seed_id("incident-event", iid, str(n)), incident_id=iid, tenant_id=tid,
                                     occurred_at=ts, event_type=etype, source=source, summary=summary,
                                     details={"synthetic": True}))
            for n, (svc, ts, level, message) in enumerate(spec["logs"]):
                db.add(LogEvent(id=seed_id("log", iid, str(n)), tenant_id=tid, service_id=seed_id("service", tid, svc),
                                incident_id=iid, ts=ts, level=level, message=message, attributes={"synthetic": True}))
    db.flush()
    return created


def _seed_knowledge(db: Session, container: Container) -> int:
    created = 0
    s = container.settings
    for tid, docs in data.KNOWLEDGE.items():
        specs: list[tuple[str, str, bytes, str, str, str, list[str], list[str]]] = [
            (key, fname, (KNOWLEDGE_DIR / fname).read_bytes(), title, version, cls, roles, tags)
            for key, fname, title, version, cls, roles, tags in docs
        ]
        if tid == data.CONTOSO:
            specs.append(("STD-CHG-014", "STD-CHG-014_change_management_standard.pdf",
                          build_text_pdf(data.CHANGE_STANDARD_PDF_LINES), "Change Management Standard", "3.0", "internal",
                          data.ALL, ["change-management", "policy"]))
        for key, fname, payload, title, version, cls, roles, tags in specs:
            existing = db.execute(select(KnowledgeDocument).where(
                KnowledgeDocument.tenant_id == tid, KnowledgeDocument.doc_key == key,
                KnowledgeDocument.version == version)).scalar_one_or_none()
            if existing is not None:
                if existing.deleted_at is None and existing.index_version != s.index_version:
                    container.ingestion.reindex(db, existing, actor=None)
                continue
            container.ingestion.ingest(db, IngestRequest(
                filename=fname, data=payload, title=title, doc_key=key, version=version,
                classification=Classification(cls), allowed_roles=roles, tags=tags,
                source=f"seed:knowledge/{fname}"), tenant_id=tid, actor=None)
            created += 1
    db.flush()
    return created


def seed_all(db: Session, container: Container) -> dict[str, Any]:
    users = _seed_identity(db, container)
    _seed_services(db)
    incidents = _seed_incidents(db)
    docs = _seed_knowledge(db, container)
    db.commit()
    register_versions(db, container)
    summary = {"users_created": users, "incidents_created": incidents, "documents_ingested": docs,
               "tenants": len(data.TENANTS)}
    log.info("seed complete", extra=summary)
    return summary


def reset_demo(db: Session, container: Container, *, actor: Actor | None) -> dict[str, Any]:
    """Restore the synthetic baseline. Audit events and evaluation history are preserved."""
    runs = select(InvestigationRun.id).where(InvestigationRun.tenant_id.in_(DEMO_TENANTS))
    for tenant_scoped_model in (Approval, ActionRecord):
        db.execute(delete(tenant_scoped_model).where(tenant_scoped_model.tenant_id.in_(DEMO_TENANTS)))
    for run_scoped_model in (Evidence, InvestigationEvent):
        db.execute(delete(run_scoped_model).where(run_scoped_model.investigation_id.in_(runs)))
    for log_model in (ToolCall, LLMCall, PolicyDecisionRecord, RetrievalLog):
        db.execute(delete(log_model).where(log_model.tenant_id.in_(DEMO_TENANTS)))
    db.execute(delete(InvestigationRun).where(InvestigationRun.tenant_id.in_(DEMO_TENANTS)))
    db.execute(delete(DemoFlag))
    db.execute(delete(LogEvent).where(LogEvent.tenant_id.in_(DEMO_TENANTS)))
    db.execute(delete(IncidentEvent).where(IncidentEvent.tenant_id.in_(DEMO_TENANTS)))
    db.execute(delete(Incident).where(Incident.tenant_id.in_(DEMO_TENANTS)))
    db.execute(delete(ServiceDependency).where(ServiceDependency.tenant_id.in_(DEMO_TENANTS)))
    db.execute(delete(Service).where(Service.tenant_id.in_(DEMO_TENANTS)))
    doc_ids = select(KnowledgeDocument.id).where(KnowledgeDocument.tenant_id.in_(DEMO_TENANTS))
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id.in_(doc_ids)))
    db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.tenant_id.in_(DEMO_TENANTS)))
    db.flush()
    summary = seed_all(db, container)
    for tid in DEMO_TENANTS:
        record_audit(db, tenant_id=tid, action="demo.reset", resource_type="demo", actor=actor,
                     details={"restored": summary, "at": utcnow().isoformat()})
    db.commit()
    return summary
