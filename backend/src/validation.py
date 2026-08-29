from __future__ import annotations

import io
import os
import threading
from pathlib import Path

import magic
import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB (user uploads)
# Framework/reference documents (downloaded PDFs, e.g. the 31MB AI Verify
# Assurance Pilot report) are not user uploads — a larger cap keeps the
# user-facing 25MB upload limit while not blocking legitimate reference
# material. Enforced only in the ingestion path, never on /upload.
MAX_FRAMEWORK_FILE_SIZE_BYTES = 200 * 1024 * 1024  # 200 MB
ALLOWED_MIME_TYPES = {"application/pdf"}
PDF_MAGIC_BYTES = b"%PDF-"

# Meridian accepts arbitrary PDFs from strangers, so the parser is an attack
# surface and not merely an inconvenience. pypdf on a malformed or
# maliciously-compressed file consumes unbounded CPU and memory, and it does
# it inside a worker thread that the request cannot cancel.
#
# A page cap costs nothing on legitimate input: the largest instrument in the
# corpus, the EU AI Act, is 144 pages. 1,500 leaves an order of magnitude of
# headroom while refusing a file whose page tree has been inflated to millions
# of entries.
MAX_PAGE_COUNT = int(os.getenv("MAX_PDF_PAGE_COUNT", "1500"))

# Wall-clock ceiling on text extraction. A decompression bomb passes every
# check above — correct magic bytes, correct MIME, plausible size — and then
# expands during extraction. Without a deadline the worker is simply gone.
PARSE_TIMEOUT_SECONDS = float(os.getenv("PDF_PARSE_TIMEOUT_SECONDS", "60"))


class ValidationResult(BaseModel):
    valid: bool
    error_type: str | None = None
    error_message: str | None = None
    ocr_warning: bool = False


def validate_pdf_file(
    file_bytes: bytes, filename: str, max_file_size: int | None = None
) -> ValidationResult:
    if max_file_size is None:
        max_file_size = MAX_FILE_SIZE_BYTES

    if len(file_bytes) > max_file_size:
        return ValidationResult(
            valid=False,
            error_type="file_too_large",
            error_message=f"File exceeds the {max_file_size // (1024 * 1024)}MB limit.",
        )
    if not file_bytes:
        return ValidationResult(
            valid=False,
            error_type="empty_file",
            error_message="Uploaded file is empty.",
        )

    if not file_bytes.startswith(PDF_MAGIC_BYTES):
        return ValidationResult(
            valid=False,
            error_type="wrong_file_type",
            error_message="Only PDF files are supported.",
        )

    mime_type = magic.from_buffer(file_bytes, mime=True)
    if mime_type not in ALLOWED_MIME_TYPES:
        return ValidationResult(
            valid=False,
            error_type="wrong_file_type",
            error_message="Only PDF files are supported.",
        )

    page_count, page_error = _page_count(file_bytes)
    if page_error:
        return ValidationResult(
            valid=False,
            error_type="malformed_pdf",
            error_message="This PDF could not be read. It may be corrupt or truncated.",
        )
    if page_count > MAX_PAGE_COUNT:
        return ValidationResult(
            valid=False,
            error_type="too_many_pages",
            error_message=(
                f"This PDF has {page_count} pages, above the {MAX_PAGE_COUNT}-page limit."
            ),
        )

    password_protected = _check_password_protected(file_bytes)
    if password_protected:
        return ValidationResult(
            valid=False,
            error_type="password_protected",
            error_message="This PDF is password-protected. Please upload an unlocked version.",
        )

    text_content, is_scanned = _extract_text_and_detect_scan(file_bytes)
    if not text_content or not text_content.strip():
        if is_scanned:
            return ValidationResult(
                valid=False,
                error_type="scanned_document",
                error_message="This appears to be a scanned document. OCR may be required before analysis — results may be incomplete.",
                ocr_warning=True,
            )
        return ValidationResult(
            valid=False,
            error_type="empty_document",
            error_message="This document appears to be empty or contains no readable text.",
        )

    return ValidationResult(valid=True)


def _page_count(file_bytes: bytes) -> tuple[int, bool]:
    """(pages, failed). Reading the page tree is cheap; extraction is not."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            # Page count is unreadable while encrypted; the dedicated
            # password check below reports it properly.
            return 0, False
        return len(reader.pages), False
    except Exception as exc:
        logger.warning("pdf_page_count_failed", error=str(exc))
        return 0, True


def _check_password_protected(file_bytes: bytes) -> bool:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        if reader.is_encrypted:
            return True
        return False
    except Exception:
        return False


def _extract_text_and_detect_scan(file_bytes: bytes) -> tuple[str, bool]:
    """Extract text under a wall-clock deadline.

    The work runs on a daemon thread so a page that never returns cannot pin
    the request. The thread is abandoned rather than killed — Python has no
    safe way to kill one — but daemon status means it cannot hold the process
    open, and the caller gets a clean rejection instead of a hung worker.
    """
    result: list[tuple[str, bool]] = []

    def _run() -> None:
        result.append(_extract_text_and_detect_scan_unbounded(file_bytes))

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout=PARSE_TIMEOUT_SECONDS)
    if worker.is_alive() or not result:
        logger.error("pdf_extraction_timeout", timeout_seconds=PARSE_TIMEOUT_SECONDS)
        return "", False
    return result[0]


def _extract_text_and_detect_scan_unbounded(file_bytes: bytes) -> tuple[str, bool]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        text_parts: list[str] = []
        total_chars = 0
        for page in reader.pages:
            extracted = page.extract_text() or ""
            text_parts.append(extracted)
            total_chars += len(extracted.strip())

        full_text = "\n".join(text_parts)

        num_pages = len(reader.pages)
        is_scanned = num_pages > 0 and total_chars < num_pages * 10

        return full_text, is_scanned
    except Exception as exc:
        logger.error("pdf_extraction_failed", error=str(exc))
        return "", False


def validate_file_path(file_path: Path, max_file_size: int | None = None) -> ValidationResult:
    if not file_path.exists():
        return ValidationResult(
            valid=False,
            error_type="file_not_found",
            error_message="File not found at the specified path.",
        )
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    return validate_pdf_file(file_bytes, file_path.name, max_file_size=max_file_size)
