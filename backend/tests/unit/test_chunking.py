"""
Unit tests for structure-aware chunking.
"""

import pytest
from src.ingestion import (
    _deterministic_chunk_id,
    structure_aware_split,
    recursive_character_split,
    Chunk,
)


class TestStructureAwareSplit:
    def test_single_section(self):
        pages = [
            {"page_number": 1, "text": "Introduction\nThis is the intro content.\nIt continues here."},
        ]
        sections = structure_aware_split(pages)
        assert len(sections) >= 1
        assert "Introduction" in sections[0]["text"] or sections[0]["section_title"] is not None

    def test_multiple_sections_by_header(self):
        # Each section carries enough real content to exceed the
        # MIN_SECTION_CHARS merge threshold (250 chars), so the numbered
        # headings are preserved as separate sections instead of being
        # collapsed into the previous one by the small-section merger.
        overview_content = (
            "This section provides a high-level overview of the policy. "
            "It outlines the objectives, scope, and intended audience of "
            "the framework, summarising the key commitments that the "
            "document makes and the governance structures that will be "
            "responsible for delivering them."
        )
        definitions_content = (
            "This section defines the core terms used throughout the "
            "document, including the precise meaning of each concept and "
            "how the terms relate to one another. The definitions are "
            "intended to ensure consistent interpretation of the policy "
            "across different implementing bodies and jurisdictions."
        )
        pages = [
            {
                "page_number": 1,
                "text": f"1. Overview\n{overview_content}\n2. Definitions\n{definitions_content}",
            },
        ]
        sections = structure_aware_split(pages)
        titles = [s["section_title"] for s in sections if s["section_title"]]
        assert len(sections) >= 2

    def test_no_structure_produces_one_section_per_page(self):
        pages = [
            {"page_number": 1, "text": "Just some continuous text without headers."},
            {"page_number": 2, "text": "More continuous text on the next page."},
        ]
        sections = structure_aware_split(pages)
        assert len(sections) >= 1

    def test_section_by_article_keyword(self):
        pages = [
            {"page_number": 1, "text": "Article 1\nThis is article one.\nArticle 2\nThis is article two."},
        ]
        sections = structure_aware_split(pages)
        article_sections = [
            s for s in sections
            if s["section_title"] and "Article" in s["section_title"]
        ]
        assert len(article_sections) >= 1


class TestRecursiveCharacterSplit:
    def test_short_text_no_split(self):
        chunks = recursive_character_split(
            text="Short text under limit.",
            metadata_base={"doc_id": "test"},
            section_title="Test",
            page_number=1,
            framework_name="OECD",
        )
        assert len(chunks) == 1
        assert chunks[0].text == "Short text under limit."

    def test_long_text_splits_into_multiple_chunks(self):
        text = "Paragraph one.\n\n" * 500
        chunks = recursive_character_split(
            text=text,
            metadata_base={"doc_id": "test"},
            section_title="Long Section",
            page_number=1,
            framework_name="UNESCO",
        )
        assert len(chunks) > 1

    def test_chunks_have_metadata(self):
        chunks = recursive_character_split(
            text="Some text.",
            metadata_base={"doc_id": "test123", "source_file": "test.pdf"},
            section_title="Section A",
            page_number=3,
            framework_name="OECD",
        )
        assert len(chunks) == 1
        c = chunks[0]
        assert c.chunk_id is not None
        assert c.section_title == "Section A"
        assert c.page_number == 3
        assert c.framework_name == "OECD"
        assert c.metadata["doc_id"] == "test123"
        assert c.metadata["source_file"] == "test.pdf"

    def test_chunk_id_is_uuid(self):
        import uuid
        chunks = recursive_character_split(
            text="Test.",
            metadata_base={"doc_id": "test"},
            section_title="T",
            page_number=1,
            framework_name="Test",
        )
        assert len(chunks) == 1
        uuid.UUID(chunks[0].chunk_id)

    def test_overlap_between_chunks(self):
        text = "Word. " * 3000
        chunks = recursive_character_split(
            text=text,
            metadata_base={"doc_id": "test"},
            section_title="Overlap",
            page_number=1,
            framework_name="Test",
        )
        if len(chunks) >= 2:
            chunk1_end = chunks[0].text[-100:]
            chunk2_start = chunks[1].text[:100]
            overlap = len(set(chunk1_end.split()) & set(chunk2_start.split()))
            assert overlap > 0, "Expected some overlap between consecutive chunks"


class TestDeterministicChunkIds:
    """Re-running an analysis re-ingests every document in the workspace. With
    a uuid4 per chunk an unchanged file came back under a whole new set of ids,
    so evidence restored from a cached dimension cited chunks that no longer
    existed — 11 of India's 49 citations failed the identity check while the
    dimensions themselves were fine."""

    def test_same_document_yields_same_ids(self):
        key = "ws-1||policy.pdf"
        first = [_deterministic_chunk_id(key, i, t) for i, t in enumerate(["alpha", "beta"])]
        second = [_deterministic_chunk_id(key, i, t) for i, t in enumerate(["alpha", "beta"])]
        assert first == second

    def test_different_documents_do_not_collide(self):
        a = _deterministic_chunk_id("ws-1||a.pdf", 0, "same text")
        b = _deterministic_chunk_id("ws-1||b.pdf", 0, "same text")
        assert a != b

    def test_repeated_text_stays_distinct(self):
        """Statutes repeat identical sentences; position keeps them apart."""
        a = _deterministic_chunk_id("ws-1||act.pdf", 3, "shall be prescribed")
        b = _deterministic_chunk_id("ws-1||act.pdf", 9, "shall be prescribed")
        assert a != b

    def test_edited_document_changes_the_id(self):
        before = _deterministic_chunk_id("ws-1||policy.pdf", 0, "original")
        after = _deterministic_chunk_id("ws-1||policy.pdf", 0, "revised")
        assert before != after


class TestWindowAlwaysAdvances:
    """A short chunk made the window crawl one character at a time.

    The overlap was a quarter of the MAXIMUM chunk size — a fixed 700 chars —
    rather than a quarter of the chunk actually emitted. When a sentence
    boundary landed early the chunk came out shorter than that, so
    `end - overlap_chars` fell behind `start`, the `max(..., start + 1)` guard
    took over, and the window advanced by a single character. Each pass
    re-emitted almost the same passage: the live EU AI Act index held runs of
    chunks 695, 692, 689, 686 chars long, every one a three-character shift of
    the last, and 514 of its 1,707 chunks sat in a duplicate set.

    Retrieval pays for this directly. A candidate sweep spends its budget on
    near-identical windows, so the scorer sees a fraction of the distinct
    passages the candidate count implies.
    """

    # One short sentence, then a long stretch with no sentence punctuation:
    # the last boundary inside the 2800-char window sits at ~600, well under
    # the 700-char overlap.
    EARLY_BOUNDARY_TEXT = ("A" * 598) + ". " + ("B " * 3000)

    def _chunks(self, text):
        from src.ingestion import recursive_character_split
        return recursive_character_split(text, {"source_file": "t.pdf"}, "Section", None, None)

    def test_the_window_does_not_crawl(self):
        chunks = self._chunks(self.EARLY_BOUNDARY_TEXT)
        # A 6.6k text split into ~600-2800 char windows is a couple of dozen
        # chunks at the very most. The crawl produced thousands.
        assert len(chunks) < 50, f"window crawled: {len(chunks)} chunks"

    def test_consecutive_chunks_are_not_near_identical(self):
        texts = [c.text for c in self._chunks(self.EARLY_BOUNDARY_TEXT)]
        for a, b in zip(texts, texts[1:]):
            shorter = min(len(a), len(b))
            if shorter < 50:
                continue
            # Whatever the overlap policy, one chunk must never be a
            # near-complete copy of its neighbour.
            assert not (a[:shorter] == b[:shorter] and abs(len(a) - len(b)) < 10), (
                f"near-duplicate neighbours: {len(a)} vs {len(b)} chars"
            )

    def test_no_exact_duplicate_chunks(self):
        texts = [c.text for c in self._chunks(self.EARLY_BOUNDARY_TEXT)]
        assert len(texts) == len(set(texts)), "the same passage was emitted twice"

    def test_the_whole_text_is_still_covered(self):
        """Guarding progress must not skip content."""
        chunks = self._chunks(self.EARLY_BOUNDARY_TEXT)
        joined = "".join(c.text for c in chunks)
        assert joined.count("A") >= 598
        assert joined.count("B") >= 3000
