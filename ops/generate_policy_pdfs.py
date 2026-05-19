"""Generate PDF versions of policy documents from policies/*.json.

Uses only Python stdlib — no external dependencies required.

Usage:
    python ops/generate_policy_pdfs.py
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

POLICIES_DIR = Path(__file__).parent.parent / "policies"

# Page geometry (points, 1pt = 1/72 inch)
PAGE_W, PAGE_H = 612, 792
MARGIN_L, MARGIN_R = 72, 72
MARGIN_T, MARGIN_B = 72, 72
TEXT_W = PAGE_W - MARGIN_L - MARGIN_R

# Font sizes
SIZE_TITLE = 16
SIZE_META = 10
SIZE_BODY = 11
LEADING_TITLE = 22
LEADING_META = 14
LEADING_BODY = 16

CHARS_TITLE = int(TEXT_W / (SIZE_TITLE * 0.55))
CHARS_BODY = int(TEXT_W / (SIZE_BODY * 0.52))


# ---------------------------------------------------------------------------
# Minimal PDF writer
# ---------------------------------------------------------------------------

class _PDF:
    def __init__(self):
        self._objs: list[bytes] = []
        self._offsets: list[int] = []
        self._buf = bytearray()
        self._write(b"%PDF-1.4\n")

    def _write(self, data: bytes) -> None:
        self._buf.extend(data)

    def _add_obj(self, content: bytes) -> int:
        obj_id = len(self._objs) + 1
        self._offsets.append(len(self._buf))
        self._write(f"{obj_id} 0 obj\n".encode())
        self._write(content)
        self._write(b"\nendobj\n")
        self._objs.append(content)
        return obj_id

    @staticmethod
    def _pdf_str(text: str) -> bytes:
        """Encode a string as a PDF literal string, escaping special chars."""
        out = []
        for ch in text:
            if ch == "(":
                out.append("\\(")
            elif ch == ")":
                out.append("\\)")
            elif ch == "\\":
                out.append("\\\\")
            elif ord(ch) > 127:
                out.append(f"\\{ord(ch):03o}")
            else:
                out.append(ch)
        return ("(" + "".join(out) + ")").encode("latin-1", errors="replace")

    def _stream_obj(self, content: str) -> int:
        data = content.encode("latin-1", errors="replace")
        obj = (
            f"<< /Length {len(data)} >>\nstream\n".encode()
            + data
            + b"\nendstream"
        )
        return self._add_obj(obj)

    def build(self, pages_content: list[str]) -> bytes:
        """Build PDF bytes from a list of page content streams."""
        # Font object
        font_id = self._add_obj(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
        )
        font_bold_id = self._add_obj(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
        )

        resources = (
            f"<< /Font << /F1 {font_id} 0 R /F2 {font_bold_id} 0 R >> >>"
        ).encode()

        page_ids = []
        for stream_text in pages_content:
            content_id = self._stream_obj(stream_text)
            page_id = self._add_obj(
                f"<< /Type /Page /Parent 0 0 R "
                f"/MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                f"/Contents {content_id} 0 R "
                f"/Resources {resources.decode()} >>".encode()
            )
            page_ids.append(page_id)

        # Pages dict
        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        pages_id = self._add_obj(
            f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
        )

        # Patch /Parent in each page obj — rewrite page entries
        for pid in page_ids:
            offset = self._offsets[pid - 1]
            chunk = self._buf[offset:offset + 200]
            new_chunk = chunk.replace(b"/Parent 0 0 R", f"/Parent {pages_id} 0 R".encode())
            self._buf[offset:offset + 200] = new_chunk + b" " * (len(chunk) - len(new_chunk))

        # Catalog
        catalog_id = self._add_obj(
            f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode()
        )

        # Cross-reference table
        xref_offset = len(self._buf)
        n = len(self._offsets) + 1
        self._write(f"xref\n0 {n}\n".encode())
        self._write(b"0000000000 65535 f \n")
        for off in self._offsets:
            self._write(f"{off:010d} 00000 n \n".encode())

        self._write(
            f"trailer\n<< /Size {n} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n".encode()
        )
        return bytes(self._buf)


# ---------------------------------------------------------------------------
# Page content builder
# ---------------------------------------------------------------------------

class _PageBuilder:
    def __init__(self):
        self._pages: list[str] = []
        self._lines: list[str] = []   # PDF operators for current page
        self._y = PAGE_H - MARGIN_T

    def _new_page(self) -> None:
        if self._lines:
            self._pages.append("\n".join(self._lines))
        self._lines = []
        self._y = PAGE_H - MARGIN_T

    def _ensure_space(self, needed: float) -> None:
        if self._y - needed < MARGIN_B:
            self._new_page()

    def _text_line(self, text: str, x: float, y: float, size: int, bold: bool = False) -> str:
        font = "F2" if bold else "F1"
        pdf = _PDF._pdf_str(text)
        return f"BT /{font} {size} Tf {x:.1f} {y:.1f} Td {pdf.decode('latin-1')} Tj ET"

    def add_title(self, text: str) -> None:
        self._ensure_space(LEADING_TITLE * 2)
        for line in textwrap.wrap(text, CHARS_TITLE) or [text]:
            self._ensure_space(LEADING_TITLE)
            self._lines.append(self._text_line(line, MARGIN_L, self._y, SIZE_TITLE, bold=True))
            self._y -= LEADING_TITLE
        self._y -= 6  # extra gap after title

    def add_meta(self, text: str) -> None:
        self._ensure_space(LEADING_META)
        self._lines.append(self._text_line(text, MARGIN_L, self._y, SIZE_META))
        self._y -= LEADING_META

    def add_spacer(self, pts: float = 10) -> None:
        self._y -= pts

    def add_body(self, text: str) -> None:
        for para in text.split("\n"):
            para = para.rstrip()
            if not para:
                self._y -= LEADING_BODY * 0.5
                continue
            # Detect section headers (all-caps words or numbered sections)
            is_heading = (
                para.strip().isupper()
                or (len(para) > 2 and para[0].isdigit() and para[1] in ".)")
            )
            wrap_w = CHARS_BODY - (4 if para.startswith("  ") else 0)
            wrapped = textwrap.wrap(para, wrap_w) or [para]
            for i, line in enumerate(wrapped):
                self._ensure_space(LEADING_BODY)
                bold = is_heading and i == 0
                x = MARGIN_L + (11 if para.startswith("  ") else 0)
                self._lines.append(self._text_line(line, x, self._y, SIZE_BODY, bold=bold))
                self._y -= LEADING_BODY

    def finish(self) -> list[str]:
        if self._lines:
            self._pages.append("\n".join(self._lines))
        return self._pages


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate_pdf(doc: dict) -> bytes:
    builder = _PageBuilder()

    builder.add_title(doc.get("title", "Policy Document"))
    builder.add_meta(f"Document ID: {doc.get('doc_id', '')}   |   Type: {doc.get('doc_type', '').upper()}   |   Effective: {doc.get('effective_date', '')}")
    builder.add_spacer(16)
    builder.add_body(doc.get("content", ""))

    pages = builder.finish()
    pdf = _PDF()
    return pdf.build(pages)


def main() -> None:
    POLICIES_DIR.mkdir(exist_ok=True)
    policy_files = sorted(POLICIES_DIR.glob("*.json"))
    if not policy_files:
        print(f"No JSON files found in {POLICIES_DIR}")
        return

    for path in policy_files:
        with path.open(encoding="utf-8") as f:
            doc = json.load(f)

        pdf_bytes = generate_pdf(doc)
        out_path = path.with_suffix(".pdf")
        out_path.write_bytes(pdf_bytes)
        print(f"Generated: {out_path.name}  ({len(pdf_bytes):,} bytes)")

    print(f"\nDone. {len(policy_files)} PDF(s) written to {POLICIES_DIR}/")


if __name__ == "__main__":
    main()
