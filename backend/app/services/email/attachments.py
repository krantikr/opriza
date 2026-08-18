"""Text extraction from email attachments.

Steel enquiries routinely arrive as a PDF RFQ or an Excel BOQ with an almost
empty covering email. If attachments are ignored, the extractor sees "Please
find attached" and the enquiry is lost.

Extraction never raises. An unreadable file records its reason on the
attachment row and the enquiry still reaches a human, who can open the original
themselves. Silently dropping the message would be the worse failure.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_EXTRACTED_CHARS = 20_000
MAX_PDF_PAGES = 20
MAX_SHEET_ROWS = 500

PDF_SUFFIXES = {".pdf"}
EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xls"}
TEXT_SUFFIXES = {".txt", ".csv", ".tsv", ".md", ".log"}


@dataclass(slots=True)
class ExtractionOutcome:
    text: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.text)


def _truncate(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_EXTRACTED_CHARS:
        return text
    return text[:MAX_EXTRACTED_CHARS] + "\n[... attachment truncated ...]"


def _decode(content: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def _extract_pdf(content: bytes) -> ExtractionOutcome:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dependency is declared
        return ExtractionOutcome(error="pypdf is not installed")

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001 - malformed PDFs are common
        return ExtractionOutcome(error=f"unreadable PDF: {exc}")

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            return ExtractionOutcome(error="PDF is password protected")

    pages: list[str] = []
    for index, page in enumerate(reader.pages[:MAX_PDF_PAGES], start=1):
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            logger.debug("PDF page %d extraction failed: %s", index, exc)

    text = "\n".join(p for p in pages if p.strip())
    if not text.strip():
        # Almost always a scanned document. OCR is out of scope for the MVP,
        # so say so plainly rather than pretending the attachment was empty.
        return ExtractionOutcome(error="no extractable text (likely a scanned image PDF)")
    return ExtractionOutcome(text=_truncate(text))


def _extract_excel(content: bytes) -> ExtractionOutcome:
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover - dependency is declared
        return ExtractionOutcome(error="pandas is not installed")

    try:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
    except Exception as exc:  # noqa: BLE001
        return ExtractionOutcome(error=f"unreadable spreadsheet: {exc}")

    chunks: list[str] = []
    for name, frame in sheets.items():
        if frame.empty:
            continue
        # CSV rather than a padded table: compact, unambiguous, and reads
        # cleanly as rows when handed to the extractor.
        body = frame.head(MAX_SHEET_ROWS).to_csv(index=False)
        chunks.append(f"[Sheet: {name}]\n{body}")

    if not chunks:
        return ExtractionOutcome(error="spreadsheet contains no data rows")
    return ExtractionOutcome(text=_truncate("\n\n".join(chunks)))


def _extract_delimited(content: bytes, suffix: str) -> ExtractionOutcome:
    text = _decode(content)
    if suffix == ".tsv":
        rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
        text = "\n".join(",".join(cell for cell in row) for row in rows)
    return ExtractionOutcome(text=_truncate(text)) if text.strip() else ExtractionOutcome(
        error="file is empty"
    )


def extract_text(
    filename: str, mime_type: str | None, content: bytes | None
) -> ExtractionOutcome:
    """Best-effort text extraction, dispatched on file extension then MIME type."""
    if not content:
        return ExtractionOutcome(error="attachment has no content")

    suffix = Path(filename).suffix.lower()
    mime = (mime_type or "").lower()

    if suffix in PDF_SUFFIXES or "pdf" in mime:
        return _extract_pdf(content)
    if suffix in EXCEL_SUFFIXES or "spreadsheet" in mime or "excel" in mime:
        return _extract_excel(content)
    if suffix in TEXT_SUFFIXES or mime.startswith("text/"):
        return _extract_delimited(content, suffix)

    return ExtractionOutcome(error=f"unsupported attachment type ({suffix or mime or 'unknown'})")
