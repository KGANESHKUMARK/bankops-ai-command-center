"""Strict Pydantic argument schemas for every allowlisted tool.

`extra="forbid"` rejects unexpected fields (e.g. `force`, `cmd`), identifiers are
pattern-constrained, numeric ranges are bounded and targets are literal allowlists.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ServiceKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9\-]{2,63}$")]
Uuid = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
BatchId = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3,5}-BATCH-\d{8}-[A-Z]$")]
TemplateId = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9\-]{2,40}$")]
ShortText = Annotated[str, StringConstraints(min_length=3, max_length=300, strip_whitespace=True)]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ----------------------------------------------------------------- read-only
class IncidentArgs(_Args):
    incident_id: Uuid


class ServiceArgs(_Args):
    service_key: ServiceKey


class LogsArgs(_Args):
    service_key: ServiceKey
    limit: int = Field(default=20, ge=1, le=50)
    level: Literal["INFO", "WARN", "ERROR"] | None = None


class SearchArgs(_Args):
    query: ShortText
    top_k: int = Field(default=4, ge=1, le=10)


class HistoryArgs(_Args):
    incident_id: Uuid
    limit: int = Field(default=3, ge=1, le=5)


class QueueArgs(_Args):
    queue_name: Literal["PAYMENT.SETTLEMENT.IN", "PAYMENT.SETTLEMENT.DLQ"]


class StreamArgs(_Args):
    stream: Literal["card-transactions", "cg-transaction-enricher", "risk-events", "flink-risk-aggregator", "payments-events"]


class TemplateArgs(_Args):
    template_id: TemplateId


class SchemaCompatArgs(_Args):
    subject: Literal["risk-events-value"]
    writer_version: int = Field(ge=1, le=100)
    reader_version: int = Field(ge=1, le=100)


# ------------------------------------------------------------------ mutating
class RestartRendererArgs(_Args):
    service_key: Literal["document-renderer"]
    strategy: Literal["rolling"] = "rolling"
    reason: ShortText


class ReprocessStatementArgs(_Args):
    service_key: Literal["statement-generator", "investment-statement-generator"]
    batch_id: BatchId
    max_documents: int = Field(default=5000, ge=1, le=20000)


class RestoreTemplateArgs(_Args):
    template_id: TemplateId
    restore_from_version: Annotated[str, StringConstraints(pattern=r"^v\d{1,3}$")]


class RestartMqConsumerArgs(_Args):
    consumer: Literal["mq-settlement-consumer"]
    channel: Literal["SETTLEMENT.SVRCONN"]


class ScaleConsumerArgs(_Args):
    consumer_group: Literal["cg-transaction-enricher"]
    target_replicas: int = Field(ge=1, le=12)


class ReplayDlqArgs(_Args):
    source: Literal["card-transactions.dlq", "PAYMENT.SETTLEMENT.DLQ"]
    max_events: int = Field(ge=1, le=500)
    idempotency_check: Literal[True] = True


class RestartFlinkArgs(_Args):
    job_name: Literal["flink-risk-aggregator"]
    checkpoint: Literal["latest"] = "latest"
    pin_reader_schema_version: int = Field(ge=1, le=100)


class RerunSnowflakeArgs(_Args):
    pipeline: Literal["snowpipe-card-settlements"]
    task: Literal["LOAD_CARD_SETTLEMENTS"]


class RerunDqArgs(_Args):
    suite: Literal["regulatory-daily-positions"]
