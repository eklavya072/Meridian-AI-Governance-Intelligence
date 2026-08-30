"""Chunking internals and the deterministic id scheme.

Two of the worst silent defects in this codebase lived here: a stride that
advanced one character at a time, and chunk ids minted fresh on every
ingestion so cached evidence pointed at chunks that no longer existed.
Neither failed a run; both degraded the output.
"""

import pytest

from src.ingestion import (
    MAX_CHUNK_CHARS,
    Chunk,
    _deterministic_chunk_id,
    _estimate_chunk_page,
    _find_sentence_boundary,
    _is_predominantly_non_english,
    ingest_document,
    parse_pdf,
    recursive_character_split,
    structure_aware_split,
)


def _split(text, **kw):
    return recursive_character_split(
        text=text,
        metadata_base={"doc_id": "d1"},
        section_title=kw.get("section_title"),
        page_number=kw.get("page_number", 1),
        framework_name=kw.get("framework_name"),
        section_pages=kw.get("section_pages"),
    )


class TestChunkStride:
    def test_short_text_is_one_chunk(self):
        chunks = _split("A short passage.")

        assert len(chunks) == 1
        assert chunks[0].text == "A short passage."

    def test_a_long_document_is_split(self):
        text = ("This is a sentence about governance. " * 400).strip()

        chunks = _split(text)

        assert len(chunks) > 1

    def test_the_window_always_advances(self):
        """The regression that mattered most.

        overlap was a quarter of the MAXIMUM chunk size rather than of the
        chunk actually emitted, so a sentence boundary landing 101 chars past
        `start` put `end - overlap` BEHIND `start`, the `start + 1` floor took
        over, and the window crawled forward one character at a time —
        re-emitting almost the same passage on every pass. The EU AI Act
        carried runs of chunks 695/692/689 chars long, 514 of 1,707 in a
        duplicate set.
        """
        # Short sentences force early boundaries, which is what triggered it.
        text = ("Short. " * 3000).strip()

        chunks = _split(text)

        assert len(chunks) < 200, "the window is barely advancing"

    def test_no_chunk_exceeds_the_maximum(self):
        text = ("A governance sentence of moderate length. " * 300).strip()

        for chunk in _split(text):
            assert len(chunk.text) <= MAX_CHUNK_CHARS + 50

    def test_duplicate_text_is_not_re_emitted_wholesale(self):
        text = ("Providers shall maintain records. " * 500).strip()

        chunks = _split(text)
        texts = [c.text for c in chunks]

        # Some overlap is intended (25%); wholesale duplication is the bug.
        assert len(set(texts)) > len(texts) * 0.5

    def test_indexed_characters_stay_near_the_source_length(self):
        text = ("Sentence number one is here. " * 400).strip()

        total = sum(len(c.text) for c in _split(text))

        # A clean 25% overlap gives ~1.25x. Far above that means the window
        # is re-emitting; far below means content is being skipped.
        assert len(text) <= total <= len(text) * 1.6


class TestSentenceBoundary:
    def test_a_boundary_is_found_at_a_sentence_end(self):
        text = "First sentence here. Second sentence here. Third one."

        boundary = _find_sentence_boundary(text, 0, len(text))

        assert text[:boundary].rstrip().endswith(".")

    def test_the_boundary_never_precedes_the_start(self):
        text = "A. " * 50

        assert _find_sentence_boundary(text, 10, 40) > 10

    def test_text_with_no_boundary_returns_the_maximum(self):
        text = "x" * 500

        assert _find_sentence_boundary(text, 0, 300) == 300


class TestDeterministicChunkIds:
    def test_the_same_bytes_produce_the_same_id(self):
        first = _deterministic_chunk_id("doc-key", 3, "the chunk text")
        second = _deterministic_chunk_id("doc-key", 3, "the chunk text")

        # Re-running re-ingests every document. With uuid4, an unchanged file
        # came back under entirely new ids and orphaned the evidence a cached
        # dimension had carried over — India run 2 lost 11 of 49 citations.
        assert first == second

    def test_different_text_produces_a_different_id(self):
        assert _deterministic_chunk_id("k", 1, "alpha") != _deterministic_chunk_id("k", 1, "beta")

    def test_different_ordinals_produce_different_ids(self):
        # Statutes repeat identical sentences, so text alone is not enough.
        assert _deterministic_chunk_id("k", 1, "same") != _deterministic_chunk_id("k", 2, "same")

    def test_different_documents_produce_different_ids(self):
        assert _deterministic_chunk_id("a", 1, "same") != _deterministic_chunk_id("b", 1, "same")

    def test_the_id_is_a_uuid_string(self):
        import uuid

        uuid.UUID(_deterministic_chunk_id("k", 0, "text"))


class TestPageEstimation:
    def test_a_single_page_section_reports_that_page(self):
        assert _estimate_chunk_page(0, 100, [7]) == 7

    def test_a_chunk_early_in_a_span_lands_near_the_first_page(self):
        assert _estimate_chunk_page(0, 100, [4, 5, 6]) == 4

    def test_a_chunk_late_in_a_span_reaches_the_last_page(self):
        # Truncation made the last page unreachable: int(0.99 * 2) == 1, so a
        # chunk 99% through a 4-6 span was attributed to page 5. Page numbers
        # feed verify_citation's page check, so that off-by-one turned correct
        # citations into page mismatches.
        assert _estimate_chunk_page(99, 100, [4, 5, 6]) == 6

    def test_the_estimate_stays_inside_the_section(self):
        for start in range(0, 101, 5):
            page = _estimate_chunk_page(start, 100, [4, 5, 6])
            assert 4 <= page <= 6

    def test_no_pages_yields_none(self):
        assert _estimate_chunk_page(0, 100, []) is None


class TestNonEnglishFilter:
    def test_english_text_is_kept(self):
        text = (
            "The provider shall ensure that the system is transparent and that "
            "the deployer is able to interpret the output of the model."
        )

        assert not _is_predominantly_non_english(text)

    def test_french_text_is_flagged(self):
        text = (
            "Le fournisseur doit garantir que le systeme est transparent et que "
            "les utilisateurs peuvent interpreter les resultats du modele dans "
            "le cadre de la reglementation."
        )

        assert _is_predominantly_non_english(text)

    def test_a_short_fragment_is_never_flagged(self):
        # Too little signal to judge; dropping it would lose real content.
        assert not _is_predominantly_non_english("Le systeme")

    def test_english_with_a_few_foreign_words_survives(self):
        text = (
            "The regulation uses the term acquis and the phrase raison d'etre "
            "but the provision itself is written in English and applies to all "
            "providers of high risk systems."
        )

        assert not _is_predominantly_non_english(text)


class TestStructureAwareSplit:
    def test_headed_sections_are_detected(self):
        pages = [
            {"page_number": 1, "text": "Article 1\nScope of this Act.\nArticle 2\nDefinitions."}
        ]

        sections = structure_aware_split(pages)

        assert len(sections) >= 1

    def test_a_document_with_no_structure_falls_back_to_pages(self):
        pages = [
            {"page_number": 1, "text": "flowing prose without headings " * 20},
            {"page_number": 2, "text": "more flowing prose " * 20},
        ]

        sections = structure_aware_split(pages)

        assert sections
        assert all(s["text"] for s in sections)

    def test_tiny_sections_are_merged(self):
        pages = [{"page_number": 1, "text": "A\nB\nC\nD\n" + ("long body text " * 40)}]

        sections = structure_aware_split(pages)

        # Otherwise a heading-per-line document produces hundreds of
        # near-empty sections and starves retrieval.
        assert len(sections) < 20

    def test_every_section_records_its_pages(self):
        pages = [{"page_number": 3, "text": "Article 1\n" + ("body " * 100)}]

        for section in structure_aware_split(pages):
            assert section["pages"]


class TestParsePdf:
    def test_a_real_pdf_is_parsed_into_pages(self, tmp_path):
        pytest.importorskip("pypdf")
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.add_blank_page(width=200, height=200)
        path = tmp_path / "two-pages.pdf"
        with open(path, "wb") as fh:
            writer.write(fh)

        pages = parse_pdf(path)

        assert len(pages) == 2
        assert pages[0]["page_number"] == 1

    def test_a_corrupt_pdf_raises_rather_than_returning_garbage(self, tmp_path):
        from pypdf.errors import PyPdfError

        path = tmp_path / "broken.pdf"
        path.write_bytes(b"%PDF-1.7\ntruncated")

        # Silently returning empty pages would score the document as
        # "no readable text" instead of reporting a corrupt file.
        with pytest.raises((PyPdfError, EOFError, ValueError)):
            parse_pdf(path)


class TestIngestDocument:
    def test_a_file_failing_validation_is_refused(self, tmp_path):
        path = tmp_path / "not.pdf"
        path.write_bytes(b"definitely not a pdf")

        with pytest.raises(ValueError, match="Validation failed"):
            ingest_document(path)

    def test_a_missing_file_is_refused(self, tmp_path):
        with pytest.raises(ValueError):
            ingest_document(tmp_path / "absent.pdf")


class TestChunkModel:
    def test_a_chunk_carries_its_workspace(self):
        chunk = Chunk(chunk_id="c1", text="t", metadata={}, workspace_id="w1")

        assert chunk.workspace_id == "w1"

    def test_page_number_is_optional(self):
        assert Chunk(chunk_id="c1", text="t", metadata={}).page_number is None
