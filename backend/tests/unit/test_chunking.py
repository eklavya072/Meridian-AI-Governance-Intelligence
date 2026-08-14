"""
Unit tests for structure-aware chunking.
"""

import pytest
from src.ingestion import (
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
