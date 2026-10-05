"""Minimal, dependency-free PDF writer used to produce the synthetic PDF runbook.

Generates a valid single-font, multi-page PDF 1.4 file with text-only content so
the PDF ingestion path (pypdf extraction) is exercised without shipping binaries.
"""

from __future__ import annotations

import textwrap


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_text_pdf(lines: list[str], *, lines_per_page: int = 46, wrap: int = 92) -> bytes:
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(textwrap.wrap(line, wrap) or [""])
    pages = [wrapped[i : i + lines_per_page] for i in range(0, len(wrapped), lines_per_page)] or [[""]]

    objects: list[bytes] = []
    font_id = 3
    page_ids: list[int] = []
    next_id = 4
    page_objs: list[tuple[int, int, bytes]] = []
    for page_lines in pages:
        ops = ["BT", "/F1 10 Tf", "13 TL", "50 790 Td"]
        for text in page_lines:
            ops.append(f"({_escape(text.encode('latin-1', 'replace').decode('latin-1'))}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        page_id, content_id = next_id, next_id + 1
        next_id += 2
        page_ids.append(page_id)
        page_objs.append((page_id, content_id, stream))

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_id, content_id, stream in page_objs:
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>".encode()
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
