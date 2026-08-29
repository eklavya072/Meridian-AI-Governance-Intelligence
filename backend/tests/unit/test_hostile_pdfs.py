"""Hostile uploads must fail cleanly, quickly, and with a useful error.

Meridian accepts arbitrary PDFs from strangers, so pypdf is an attack surface
rather than an inconvenience. Every case below asserts three things: the file
is rejected, the error names something a user can act on, and the rejection
happens fast enough that a worker was never pinned.
"""

import io
import time
import zlib

import pytest

from src.validation import (
    MAX_FILE_SIZE_BYTES,
    MAX_PAGE_COUNT,
    validate_pdf_file,
)

# Generous relative to the real work (a legitimate 144-page instrument
# validates in well under a second) but far below the point at which a
# request has effectively hung.
BUDGET_SECONDS = 20.0


def _elapsed(fn):
    start = time.monotonic()
    result = fn()
    return result, time.monotonic() - start


def test_zero_byte_file():
    result, secs = _elapsed(lambda: validate_pdf_file(b"", "empty.pdf"))

    assert not result.valid
    assert result.error_type == "empty_file"
    assert secs < BUDGET_SECONDS


def test_not_a_pdf_despite_the_extension():
    # Extension and client-supplied MIME are both attacker-controlled; the
    # check reads the bytes.
    payload = b"MZ\x90\x00" + b"\x00" * 1024  # a PE header

    result, secs = _elapsed(lambda: validate_pdf_file(payload, "totally-a.pdf"))

    assert not result.valid
    assert result.error_type == "wrong_file_type"
    assert secs < BUDGET_SECONDS


def test_pdf_magic_bytes_on_a_non_pdf_body():
    # Passes the cheap magic-byte check, fails libmagic's real inspection or
    # the parse — either way it must not be accepted.
    payload = b"%PDF-1.4\n" + b"\x00\xff" * 4096

    result, secs = _elapsed(lambda: validate_pdf_file(payload, "fake.pdf"))

    assert not result.valid
    assert secs < BUDGET_SECONDS


def test_truncated_pdf():
    payload = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"

    result, secs = _elapsed(lambda: validate_pdf_file(payload, "truncated.pdf"))

    assert not result.valid
    assert result.error_type in ("malformed_pdf", "empty_document", "wrong_file_type")
    assert result.error_message
    assert secs < BUDGET_SECONDS


def test_oversized_file_is_rejected_by_size_not_parsed():
    # One byte over the cap. The point is that the size check fires before
    # anything tries to parse it.
    payload = b"%PDF-1.4\n" + b"A" * MAX_FILE_SIZE_BYTES

    result, secs = _elapsed(lambda: validate_pdf_file(payload, "huge.pdf"))

    assert not result.valid
    assert result.error_type == "file_too_large"
    assert secs < BUDGET_SECONDS


def test_compression_bomb_does_not_expand_unbounded():
    """A small file whose streams inflate enormously.

    zlib expands 50MB of zeros to a few KB. A parser that decompresses every
    stream eagerly, with no ceiling, is how a 20KB upload becomes an OOM.
    """
    bomb = zlib.compress(b"\x00" * (50 * 1024 * 1024), level=9)
    payload = (
        b"%PDF-1.7\n"
        b"1 0 obj\n<< /Length " + str(len(bomb)).encode() + b" /Filter /FlateDecode >>\n"
        b"stream\n" + bomb + b"\nendstream\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
    )

    assert len(payload) < 1024 * 1024, "the bomb must be small on disk to be a bomb"

    result, secs = _elapsed(lambda: validate_pdf_file(payload, "bomb.pdf"))

    assert not result.valid
    assert result.error_message
    assert secs < BUDGET_SECONDS


def test_declared_page_count_far_above_the_cap_is_refused():
    """A page tree claiming more pages than the cap allows.

    The cap exists so a file cannot make the extractor walk millions of page
    objects. The largest real instrument in the corpus, the EU AI Act, is 144
    pages, so 1,500 refuses only pathological input.
    """
    assert MAX_PAGE_COUNT >= 500, "the cap must leave room for real statutes"

    kids = b" ".join(f"{i} 0 R".encode() for i in range(3, 3 + 20))
    payload = (
        b"%PDF-1.7\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Count 99999999 /Kids [" + kids + b"] >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
    )

    result, secs = _elapsed(lambda: validate_pdf_file(payload, "many-pages.pdf"))

    # Either the page cap or the malformed-structure check catches it; what
    # must not happen is acceptance, or a walk that never returns.
    assert not result.valid
    assert secs < BUDGET_SECONDS


def test_password_protected_pdf_is_named_as_such():
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("correct horse battery staple")
    buf = io.BytesIO()
    writer.write(buf)

    result, secs = _elapsed(lambda: validate_pdf_file(buf.getvalue(), "locked.pdf"))

    assert not result.valid
    # The user can act on this one, so it must not be flattened into a
    # generic "could not read".
    assert result.error_type == "password_protected"
    assert "password" in result.error_message.lower()
    assert secs < BUDGET_SECONDS


def test_deeply_nested_page_tree_terminates():
    """Recursive /Pages references. A naive walk never returns."""
    objs = [b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"]
    # 2 -> 3 -> 4 ... -> 2, a cycle.
    for i in range(2, 60):
        nxt = i + 1 if i < 59 else 2
        objs.append(f"{i} 0 obj\n<< /Type /Pages /Count 1 /Kids [{nxt} 0 R] >>\nendobj\n".encode())
    payload = b"%PDF-1.7\n" + b"".join(objs) + b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"

    result, secs = _elapsed(lambda: validate_pdf_file(payload, "cyclic.pdf"))

    assert not result.valid
    assert secs < BUDGET_SECONDS


def test_every_rejection_carries_a_message():
    """No hostile input may produce a bare `valid=False` with no explanation.

    A rejection with no reason reaches the user as an unexplained failure and
    reaches the operator as an unactionable log line.
    """
    payloads = {
        "empty": b"",
        "not-pdf": b"not a pdf at all",
        "truncated": b"%PDF-1.7\n1 0 obj\n",
        "magic-only": b"%PDF-",
    }

    for name, payload in payloads.items():
        result = validate_pdf_file(payload, f"{name}.pdf")

        assert not result.valid, name
        assert result.error_type, name
        assert result.error_message, name
