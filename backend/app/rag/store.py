"""Vector similarity search over authorization-filtered chunks.

Authorization and tenant filters are applied *in SQL* before any similarity is
computed, so unauthorized content never enters the candidate set.

- PostgreSQL: pgvector cosine distance (`<=>`) ordered in the database.
- SQLite fallback: candidate embeddings are loaded (bounded by
  `retrieval_max_candidates`) and cosine similarity is computed with NumPy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import Float, Select, and_, bindparam, select
from sqlalchemy.orm import Session

from app.domain import ROLE_BITS, DocumentStatus, Role, clearance_rank
from app.models import KnowledgeChunk, KnowledgeDocument


@dataclass(frozen=True)
class ChunkFilter:
    tenant_id: str
    role: str
    index_version: str
    document_ids: tuple[str, ...] = ()
    classifications: tuple[str, ...] = ()
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def role_bit(self) -> int:
        return ROLE_BITS[Role(self.role)]

    @property
    def max_rank(self) -> int:
        return clearance_rank(self.role)


def authorized_chunk_query(f: ChunkFilter) -> Select[tuple[KnowledgeChunk]]:
    conditions = [
        KnowledgeChunk.tenant_id == f.tenant_id,
        KnowledgeDocument.tenant_id == f.tenant_id,
        KnowledgeChunk.classification_rank <= f.max_rank,
        KnowledgeChunk.allowed_roles_mask.op("&")(f.role_bit) != 0,
        KnowledgeChunk.index_version == f.index_version,
        KnowledgeDocument.status == DocumentStatus.INDEXED.value,
        KnowledgeDocument.deleted_at.is_(None),
    ]
    if f.document_ids:
        conditions.append(KnowledgeChunk.document_id.in_(f.document_ids))
    if f.classifications:
        conditions.append(KnowledgeChunk.classification.in_(f.classifications))
    return (
        select(KnowledgeChunk)
        .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
        .where(and_(*conditions))
    )


def semantic_search(
    db: Session, query_vec: list[float], f: ChunkFilter, *, k: int, max_candidates: int
) -> list[tuple[KnowledgeChunk, float]]:
    base = authorized_chunk_query(f)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        qparam = bindparam("qvec", value=query_vec, type_=KnowledgeChunk.embedding.type)
        distance = KnowledgeChunk.embedding.op("<=>", return_type=Float)(qparam)
        rows = db.execute(base.add_columns(distance.label("distance")).order_by(distance).limit(k)).all()
        return [(row[0], 1.0 - float(row[1])) for row in rows]
    chunks = list(db.execute(base.limit(max_candidates)).scalars())
    if not chunks:
        return []
    matrix = np.asarray([c.embedding for c in chunks], dtype=np.float32)
    q = np.asarray(query_vec, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(q) or 1.0)
    sims = matrix @ q / np.where(norms == 0, 1.0, norms)
    order = np.argsort(-sims)[:k]
    return [(chunks[i], float(sims[i])) for i in order]


def candidate_chunks(db: Session, f: ChunkFilter, *, max_candidates: int) -> list[KnowledgeChunk]:
    return list(db.execute(authorized_chunk_query(f).limit(max_candidates)).scalars())
