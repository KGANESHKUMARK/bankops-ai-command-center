"""Portable column types.

`EmbeddingVector` maps to pgvector's `vector(n)` on PostgreSQL and to a compact
float32 BLOB on SQLite (the documented local fallback, where similarity is
computed in Python with NumPy after SQL-side authorization filters).

`UTCDateTime` guarantees timezone-aware UTC datetimes on both backends
(SQLite has no native timezone support).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy import DateTime, LargeBinary
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class EmbeddingVector(TypeDecorator[list[float]]):
    impl = LargeBinary
    cache_ok = True

    def __init__(self, dim: int, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.dim = dim

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(LargeBinary())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        arr = np.asarray(value, dtype=np.float32)
        if arr.shape != (self.dim,):
            raise ValueError(f"embedding dimension mismatch: expected {self.dim}, got {arr.shape}")
        if dialect.name == "postgresql":
            return arr.tolist()
        return arr.tobytes()

    def process_result_value(self, value: Any, dialect: Dialect) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, bytes | bytearray | memoryview):
            return np.frombuffer(bytes(value), dtype=np.float32).tolist()
        return np.asarray(value, dtype=np.float32).tolist()
