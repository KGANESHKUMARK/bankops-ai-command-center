from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, new_id, utcnow
from app.db.types import UTCDateTime
from app.domain import Classification, IncidentStatus, ServiceStatus, Severity, sql_in
from app.models._common import JSONType


class Service(Base):
    """Synthetic service catalog entry. `metrics` holds simulated runtime state."""

    __tablename__ = "services"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key"),
        CheckConstraint(f"status IN ({sql_in(ServiceStatus)})", name="valid_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    tier: Mapped[str] = mapped_column(String(16), default="tier-2")
    owner_team: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default=ServiceStatus.HEALTHY.value)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ServiceDependency(Base):
    """`service_id` depends on `depends_on_id` (edge in the synthetic dependency map)."""

    __tablename__ = "service_dependencies"
    __table_args__ = (UniqueConstraint("service_id", "depends_on_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    depends_on_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    dependency_type: Mapped[str] = mapped_column(String(32), default="sync-http")


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number"),
        CheckConstraint(f"severity IN ({sql_in(Severity)})", name="valid_severity"),
        CheckConstraint(f"status IN ({sql_in(IncidentStatus)})", name="valid_status"),
        CheckConstraint(f"classification IN ({sql_in(Classification)})", name="valid_classification"),
        Index("ix_incidents_tenant_status", "tenant_id", "status"),
        Index("ix_incidents_tenant_detected", "tenant_id", "detected_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    number: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))
    classification: Mapped[str] = mapped_column(String(16), default=Classification.INTERNAL.value)
    primary_service_id: Mapped[str | None] = mapped_column(ForeignKey("services.id"), nullable=True)
    affected_services: Mapped[list[str]] = mapped_column(JSONType, default=list)
    owner_team: Mapped[str] = mapped_column(String(80))
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    impact: Mapped[str] = mapped_column(Text, default="")
    customer_impact: Mapped[str] = mapped_column(Text, default="")
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    scenario_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_criteria: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # Synthetic identifiers used by diagnostics (batch IDs, template IDs, queues, schema subjects...).
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    resolution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident_time", "incident_id", "occurred_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())
    event_type: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class LogEvent(Base):
    __tablename__ = "log_events"
    __table_args__ = (Index("ix_log_events_service_ts", "service_id", "ts"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    incident_id: Mapped[str | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ts: Mapped[datetime] = mapped_column(UTCDateTime())
    level: Mapped[str] = mapped_column(String(8))
    message: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
