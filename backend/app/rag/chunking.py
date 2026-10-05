"""Structure-aware chunking with configurable size and overlap.

Markdown is split on headings (the heading path becomes the chunk's `section`),
then long sections are packed paragraph-by-paragraph (sentence-level fallback)
into windows of at most `chunk_size` characters with `overlap` characters of
trailing context carried into the next chunk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_PLAIN_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+[A-Z][^\n]{2,80}|[A-Z][A-Z0-9 &/\-]{3,80})$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class TextChunk:
    index: int
    section: str
    content: str


def _split_sections_markdown(text: str, title: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    buf: list[str] = []
    current = title
    in_code = False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
        match = None if in_code else _MD_HEADING.match(line)
        if match:
            if "\n".join(buf).strip():
                sections.append((current, "\n".join(buf).strip()))
            buf = []
            level, heading = len(match.group(1)), match.group(2).strip()
            stack = [(lvl, h) for lvl, h in stack if lvl < level] + [(level, heading)]
            current = " > ".join(h for _, h in stack)
        else:
            buf.append(line)
    if "\n".join(buf).strip():
        sections.append((current, "\n".join(buf).strip()))
    return sections


def _split_sections_plain(text: str, title: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current = title
    buf: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and len(stripped) <= 90 and _PLAIN_HEADING.match(stripped):
            if "\n".join(buf).strip():
                sections.append((current, "\n".join(buf).strip()))
            buf, current = [], f"{title} > {stripped.title() if stripped.isupper() else stripped}"
        else:
            buf.append(line)
    if "\n".join(buf).strip():
        sections.append((current, "\n".join(buf).strip()))
    return sections


def _pieces(body: str, chunk_size: int) -> list[str]:
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para:
            continue
        if len(para) <= chunk_size:
            pieces.append(para)
            continue
        for sentence in _SENTENCE.split(para):
            while len(sentence) > chunk_size:
                cut = sentence.rfind(" ", 0, chunk_size)
                cut = cut if cut > chunk_size // 2 else chunk_size
                pieces.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            if sentence:
                pieces.append(sentence)
    return pieces


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    cut = text.find(" ", len(text) - overlap)
    return text[cut + 1 :] if cut != -1 else text[-overlap:]


def _pack(body: str, chunk_size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for piece in _pieces(body, chunk_size):
        candidate = f"{current}\n\n{piece}" if current else piece
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
            carry = _tail(current, overlap)
            current = f"{carry}\n\n{piece}" if carry and len(carry) + len(piece) + 2 <= chunk_size else piece
        else:
            current = piece
    if current:
        chunks.append(current)
    return chunks


def chunk_document(text: str, *, title: str, source_type: str, chunk_size: int, overlap: int) -> list[TextChunk]:
    if overlap >= chunk_size:
        raise ValueError("chunk overlap must be smaller than chunk size")
    splitter = _split_sections_markdown if source_type == "markdown" else _split_sections_plain
    out: list[TextChunk] = []
    for section, body in splitter(text, title):
        for content in _pack(body, chunk_size, overlap):
            out.append(TextChunk(index=len(out), section=section[:480], content=content))
    return out
