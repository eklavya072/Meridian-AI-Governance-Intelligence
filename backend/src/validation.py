from __future__ import annotations

import io
import magic
import structlog
from pathlib import Path
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


class ValidationResult(BaseModel):
    valid: bool
    error_type: str | None = None
    error_message: str | None = None
    ocr_warning: bool = False


def validate_pdf_file(file_bytes: bytes, filename: str, max_file_size: int | None = None) -> ValidationResult:
    if max_file_size is None:
        max_file_size = MAX_FILE_SIZE_BYTES

    if len(file_bytes) > max_file_size:
        return ValidationResult(
            valid=False,
            error_type="file_too_large",
            error_message=f"File exceeds the {max_file_size // (1024*1024)}MB limit.",
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
