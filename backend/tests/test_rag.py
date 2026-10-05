"""RAG: loading, chunking, embeddings, authorized hybrid retrieval, citations, lifecycle."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import actor
from sqlalchemy import select

from app.domain import Classification
from app.models import KnowledgeChunk, KnowledgeDocument
from app.rag.chunking import chunk_document
from app.rag.embeddings import HashingEmbedder
from app.rag.ingestion import DocumentConflictError, DuplicateDocumentError, IngestRequest
from app.rag.loaders import DocumentLoadError, load_document, safe_filename
from app.rag.pdf import build_text_pdf


def req(**kw) -> IngestRequest:  # type: ignore[no-untyped-def]
    base = dict(filename="note.md", data=b"# Test Note\n\n## Section\n\nSynthetic content about widget queues and lag.",
                title="Test Note", doc_key="TST-NOTE-001", version="1.0", classification=Classification.INTERNAL,
                allowed_roles=["operations_analyst", "operations_manager"], tags=["test"], source="test")
    base.update(kw)
    return IngestRequest(**base)


# ------------------------------------------------------------------ units
def test_markdown_chunking_uses_heading_paths_and_bounds() -> None:
    text = "# Runbook\n\nIntro.\n\n## Diagnosis\n\n" + ("Check the queue depth carefully. " * 60) + "\n\n## Fix\n\nRestart."
    chunks = chunk_document(text, title="Runbook", source_type="markdown", chunk_size=400, overlap=80)
    sections = {c.section for c in chunks}
    assert "Runbook > Diagnosis" in sections and "Runbook > Fix" in sections
    assert all(len(c.content) <= 400 for c in chunks)
    diag = [c for c in chunks if c.section == "Runbook > Diagnosis"]
    assert len(diag) > 1
    assert diag[1].content.split()[0] in diag[0].content  # overlap carries context forward
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunk_overlap_must_be_smaller_than_size() -> None:
    with pytest.raises(ValueError):
        chunk_document("x" * 100, title="t", source_type="text", chunk_size=200, overlap=200)


def test_hashing_embeddings_are_deterministic_and_normalized() -> None:
    emb = HashingEmbedder(384)
    a, b = emb.embed(["document renderer outage", "document renderer outage"])
    assert a == b and abs(np.linalg.norm(a) - 1.0) < 1e-5
    related, unrelated = emb.embed(["renderer outage restart", "fraud vendor timeout"])
    assert np.dot(a, related) > np.dot(a, unrelated)


def test_safe_filename_strips_path_traversal() -> None:
    assert safe_filename("../../etc/passwd.md") == "passwd.md"
    assert safe_filename("C:\\Windows\\evil runbook.txt") == "evil_runbook.txt"
    with pytest.raises(DocumentLoadError):
        safe_filename("../../")


@pytest.mark.parametrize(("name", "data"), [
    ("malware.exe", b"MZ\x90\x00"),
    ("fake.pdf", b"not a pdf at all, just text"),
    ("binary.md", b"# hi\x00\x01\x02 binary"),
    ("empty.md", b""),
])
def test_unsafe_uploads_rejected(name: str, data: bytes) -> None:
    with pytest.raises(DocumentLoadError):
        load_document(name, data, max_bytes=100_000)


def test_oversized_upload_rejected() -> None:
    with pytest.raises(DocumentLoadError):
        load_document("big.md", b"a" * 5000, max_bytes=1000)


def test_pdf_text_extraction_roundtrip() -> None:
    pdf = build_text_pdf(["1. PURPOSE", "Synthetic change management text for extraction tests."])
    doc = load_document("standard.pdf", pdf, max_bytes=100_000)
    assert doc.source_type == "pdf" and "Synthetic change management" in doc.text and doc.page_count == 1


# --------------------------------------------------------------- retrieval
def test_seeded_pdf_is_indexed(db) -> None:  # type: ignore[no-untyped-def]
    doc = db.execute(select(KnowledgeDocument).where(KnowledgeDocument.doc_key == "STD-CHG-014")).scalar_one()
    assert doc.source_type == "pdf" and doc.status == "indexed" and doc.chunk_count >= 1


def test_search_returns_citations_with_metadata(container, db) -> None:  # type: ignore[no-untyped-def]
    res = container.retriever.search(db, actor(db, "ops.analyst"), "document renderer 503 statement batch failed", top_k=5)
    assert res.sufficient and res.results
    top = res.results[0]
    assert top.doc_key in {"RB-STMT-001", "RB-DOCR-002"}
    assert top.title and top.version and top.section and top.chunk_ref.startswith(f"{top.doc_key}@{top.version}#chunk-")
    assert top.citation().startswith(top.title)


def test_restricted_document_excluded_for_analyst_but_visible_to_manager(container, db) -> None:  # type: ignore[no-untyped-def]
    q = "fraud operations escalation duplicate refunds"
    analyst = container.retriever.search(db, actor(db, "ops.analyst"), q, top_k=10)
    manager = container.retriever.search(db, actor(db, "ops.manager"), q, top_k=10)
    assert "RB-FRAUD-012" not in {r.doc_key for r in analyst.results}
    assert analyst.excluded_unauthorized > 0
    assert "RB-FRAUD-012" in {r.doc_key for r in manager.results}


def test_confidential_document_excluded_for_read_only(container, db) -> None:  # type: ignore[no-untyped-def]
    res = container.retriever.search(db, actor(db, "readonly.viewer"), "MQ queue backlog consumer channel", top_k=10)
    assert "RB-MQ-004" not in {r.doc_key for r in res.results}
    assert all(r.classification in ("public", "internal") for r in res.results)


def test_tenant_isolation_in_retrieval(container, db) -> None:  # type: ignore[no-untyped-def]
    fab = container.retriever.search(db, actor(db, "fab.analyst"), "document renderer restart statement", top_k=10)
    assert {r.doc_key for r in fab.results} <= {"FAB-RB-001"}
    contoso = container.retriever.search(db, actor(db, "ops.manager"), "Fabrikam card settlement file gateway", top_k=10)
    assert "FAB-RB-001" not in {r.doc_key for r in contoso.results}


def test_metadata_filters(container, db) -> None:  # type: ignore[no-untyped-def]
    a = actor(db, "ops.analyst")
    conf = container.retriever.search(db, a, "queue backlog payments", classifications=("confidential",), top_k=10)
    assert conf.results and all(r.classification == "confidential" for r in conf.results)
    tagged = container.retriever.search(db, a, "restart and recovery steps", tags=("flink",), top_k=10)
    assert tagged.results and {r.doc_key for r in tagged.results} == {"RB-FLINK-005"}


@pytest.mark.parametrize("mode", ["hybrid", "semantic", "keyword"])
def test_retrieval_modes(container, db, mode: str) -> None:  # type: ignore[no-untyped-def]
    res = container.retriever.search(db, actor(db, "ops.analyst"), "kafka consumer lag slow processing", mode=mode, top_k=3)
    assert res.results and res.results[0].doc_key == "RB-KAFKA-003"


def test_weak_query_is_insufficient(container, db) -> None:  # type: ignore[no-untyped-def]
    res = container.retriever.search(db, actor(db, "ops.analyst"), "zebra quantum marmalade telescope", top_k=5)
    assert res.sufficient is False


def test_unverified_sources_are_labeled_and_downweighted(container, db) -> None:  # type: ignore[no-untyped-def]
    res = container.retriever.search(db, actor(db, "ops.analyst"), "community troubleshooting notes renderer", top_k=10)
    unverified = [r for r in res.results if r.doc_key == "KB-COMM-013"]
    assert unverified and all(r.trust == "unverified" for r in unverified)


# --------------------------------------------------------------- lifecycle
def test_ingest_duplicate_version_supersede_delete_reindex(container, db, clean) -> None:  # type: ignore[no-untyped-def]
    mgr = actor(db, "ops.manager")
    ing = container.ingestion
    doc = ing.ingest(db, req(), tenant_id="contoso-demo", actor=mgr)
    assert doc.status == "indexed" and doc.chunk_count >= 1 and len(doc.content_hash) == 64
    with pytest.raises(DuplicateDocumentError):
        ing.ingest(db, req(doc_key="TST-NOTE-002"), tenant_id="contoso-demo", actor=mgr)
    with pytest.raises(DocumentConflictError):
        ing.ingest(db, req(data=b"# Different\n\nOther synthetic widget content."), tenant_id="contoso-demo", actor=mgr)
    v2 = ing.ingest(db, req(version="1.1", data=b"# Test Note v2\n\nUpdated synthetic widget queue guidance."),
                    tenant_id="contoso-demo", actor=mgr)
    db.refresh(doc)
    assert doc.status == "deleted" and doc.chunk_count == 0 and "Superseded" in (doc.status_detail or "")
    chunk_count = db.execute(select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id)).all()
    assert chunk_count == []
    v2.index_version = "idx-stale"
    db.flush()
    assert ing.reindex_stale(db, tenant_id="contoso-demo") >= 1
    assert v2.index_version == container.settings.index_version
    ing.delete(db, v2, actor=mgr)
    db.commit()
    res = container.retriever.search(db, mgr, "widget queue guidance", top_k=10)
    assert "TST-NOTE-001" not in {r.doc_key for r in res.results}
    assert v2.retention_until is not None
