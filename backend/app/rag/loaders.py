"""Safe loading and text extraction for approved knowledge formats (Markdown, text, PDF)."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from app.rag.text import normalize_text

ALLOWED_EXTENSIONS = {".md": "markdown", ".markdown": "markdown", ".txt": "text", ".pdf": "pdf"}
MAX_PDF_PAGES = 60
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class DocumentLoadError(ValueError):
    """Raised with a user-safe message when a document cannot be accepted."""


@dataclass
class LoadedDocument:
    filename: str
    source_type: str
    text: str
    byte_size: int
    page_count: int | None = None


def safe_filename(name: str) -> str:
    """Strip any directory components and unsafe characters (path traversal defense)."""
    base = re.split(r"[\\/]", name or "")[-1].strip()
    base = _SAFE_NAME.sub("_", base)[:120].lstrip(".")
    if not base or "." not in base:
        raise DocumentLoadError("Invalid file name.")
    return base


def detect_source_type(filename: str, data: bytes) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower()
    source_type = ALLOWED_EXTENSIONS.get(ext)
    if source_type is None:
        raise DocumentLoadError("Unsupported file type. Allowed: .md, .markdown, .txt, .pdf")
    if source_type == "pdf":
        if not data.startswith(b"%PDF-"):
            raise DocumentLoadError("File content is not a valid PDF.")
    elif b"\x00" in data:
        raise DocumentLoadError("Binary content is not allowed for text documents.")
    return source_type


def _extract_pdf(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise DocumentLoadError("Encrypted PDFs are not supported.")
        pages = reader.pages
        if len(pages) > MAX_PDF_PAGES:
            raise DocumentLoadError(f"PDF exceeds the {MAX_PDF_PAGES}-page limit.")
        texts = [(page.extract_text() or "").strip() for page in pages]
    except DocumentLoadError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise DocumentLoadError("PDF could not be parsed.") from exc
    text = "\n\n".join(t for t in texts if t)
    if not text.strip():
        raise DocumentLoadError("PDF has no extractable text (scanned PDFs are not supported).")
    return text, len(texts)


def load_document(filename: str, data: bytes, *, max_bytes: int) -> LoadedDocument:
    if not data:
        raise DocumentLoadError("File is empty.")
    if len(data) > max_bytes:
        raise DocumentLoadError(f"File exceeds the maximum size of {max_bytes} bytes.")
    name = safe_filename(filename)
    source_type = detect_source_type(name, data)
    page_count = None
    if source_type == "pdf":
        raw, page_count = _extract_pdf(data)
    else:
        try:
            raw = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentLoadError("Text documents must be UTF-8 encoded.") from exc
    text = normalize_text(raw)
    if len(text) < 20:
        raise DocumentLoadError("Document has too little text to index.")
    return LoadedDocument(filename=name, source_type=source_type, text=text, byte_size=len(data), page_count=page_count)
