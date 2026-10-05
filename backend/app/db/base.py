"""Declarative base with deterministic constraint naming (portable across SQLite/PostgreSQL)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


SEED_NAMESPACE = uuid.UUID("6f1c2d3e-8a9b-4c5d-9e0f-1a2b3c4d5e6f")


def seed_id(*parts: str) -> str:
    """Deterministic UUID for seed records so seeding is idempotent."""
    return str(uuid.uuid5(SEED_NAMESPACE, "/".join(parts)))
