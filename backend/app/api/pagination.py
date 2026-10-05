from __future__ import annotations

from typing import Annotated, Any

from fastapi import Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

PageParam = Annotated[int, Query(ge=1, le=10_000, description="1-based page number")]
PageSizeParam = Annotated[int, Query(ge=1, le=100, description="Items per page (max 100)")]


def paginate(db: Session, query: Select[Any], page: int, page_size: int) -> tuple[list[Any], int]:
    total = db.execute(select(func.count()).select_from(query.order_by(None).subquery())).scalar_one()
    items = list(db.execute(query.limit(page_size).offset((page - 1) * page_size)).scalars())
    return items, int(total)
