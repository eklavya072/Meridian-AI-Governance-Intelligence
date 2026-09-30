"""The scorer's reading of two real instruments, pinned byte for byte.

tests/golden holds the EU AI Act and the UK's AI regulation white paper, with
their licences, and the reading each one produced when it was last reviewed.
Scoring is code, so the same PDF must always read the same way: a difference
here is a change in how Meridian judges real legislation, and it should be
regenerated on purpose (see tests/golden/reading.py), never by accident.
"""

import hashlib
import json

import pytest

from tests.golden.reading import DOCUMENTS, EXPECTED, HERE, read_document

EXPECTED_READING = json.loads(EXPECTED.read_text(encoding="utf-8"))


@pytest.mark.parametrize("filename", sorted(DOCUMENTS))
def test_the_reading_matches_the_snapshot(filename):
    assert read_document(filename) == EXPECTED_READING[filename]


def test_every_document_has_a_recorded_licence_and_checksum():
    licences = (HERE / "LICENSES.md").read_text(encoding="utf-8")
    for filename in DOCUMENTS:
        digest = hashlib.sha256((HERE / filename).read_bytes()).hexdigest()
        assert filename in licences
        assert digest in licences, f"{filename} changed since its licence entry was written"


def test_the_binding_statute_outreads_the_white_paper():
    # A sanity check on the snapshot itself: a regulation with penalties must
    # carry more binding provisions than a consultation paper, dimension by
    # dimension in total.
    def binding(filename):
        return sum(d["binding"] for d in EXPECTED_READING[filename]["dimensions"].values())

    assert binding("eu-ai-act-2024-1689.pdf") > 5 * binding(
        "uk-pro-innovation-ai-regulation-2023.pdf"
    )
