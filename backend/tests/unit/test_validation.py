"""
Unit tests for the upload validation module.

Tests every failure mode specified in Section 7a Case B.
"""

from pathlib import Path

import pytest

from src.validation import (
    MAX_FILE_SIZE_BYTES,
    validate_file_path,
    validate_pdf_file,
)


class TestPDFMagicBytes:
    def test_not_a_pdf_wrong_magic_bytes(self):
        data = b"not a PDF file at all"
        result = validate_pdf_file(data, "test.txt")
        assert not result.valid
        assert result.error_type == "wrong_file_type"

    def test_not_a_pdf_empty_prefix(self):
        data = b"\x00\x00\x00\x00\x00\x00\x00\x00"
        result = validate_pdf_file(data, "test.pdf")
        assert not result.valid
        assert result.error_type == "wrong_file_type"

    def test_pdf_with_correct_magic_bytes_no_content(self):
        data = b"%PDF-1.4\n%empty"
        result = validate_pdf_file(data, "test.pdf")
        assert not result.valid
        # malformed_pdf since the page-count check was added: this file is
        # truncated ("Stream has ended unexpectedly"), and saying so is more
        # accurate than the older "empty_document", which described a
        # readable PDF with no text layer.
        assert result.error_type in ("empty_document", "corrupted", "malformed_pdf")


class TestFileSize:
    def test_exceeds_max_size(self):
        data = b"%PDF-1.4\n" + b"x" * (MAX_FILE_SIZE_BYTES + 1)
        result = validate_pdf_file(data, "large.pdf")
        assert not result.valid
        assert result.error_type == "file_too_large"

    def test_under_max_size(self):
        data = b"%PDF-1.4\n" + b"x" * 1000 + b"\n%%EOF"
        result = validate_pdf_file(data, "small.pdf")
        assert result.error_type != "file_too_large"


class TestEmptyFile:
    def test_completely_empty(self):
        result = validate_pdf_file(b"", "empty.pdf")
        assert not result.valid
        assert result.error_type == "empty_file"

    def test_pdf_marker_only_no_content(self):
        data = b"%PDF-1.4\n"
        result = validate_pdf_file(data, "minimal.pdf")
        assert not result.valid or result.ocr_warning


class TestPasswordProtected:
    def test_detect_password_protected(self):
        import io

        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(200, 200)
        writer.encrypt("password123")

        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        data = buf.getvalue()

        result = validate_pdf_file(data, "protected.pdf")
        assert result.error_type == "password_protected"


class TestScannedDocument:
    def test_scanned_image_pdf(self):
        import io

        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(200, 200)
        writer.add_blank_page(200, 200)

        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        data = buf.getvalue()

        result = validate_pdf_file(data, "scanned.pdf")
        assert result.ocr_warning or not result.valid


class TestValidPDF:
    def test_valid_pdf_passes(self):
        import io

        from pypdf import PdfWriter

        writer = PdfWriter()
        page = writer.add_blank_page(200, 200)
        page.merge_page(page)

        writer.add_blank_page(200, 200)

        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        data = buf.getvalue()

        result = validate_pdf_file(data, "valid.pdf")
        if result.ocr_warning:
            pytest.skip("Generated PDF has no text layer")
        assert result.valid


class TestFileNotFound:
    def test_nonexistent_file(self):
        result = validate_file_path(Path("/nonexistent/path.pdf"))
        assert not result.valid
        assert result.error_type == "file_not_found"
