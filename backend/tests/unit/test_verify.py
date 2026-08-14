"""
Unit tests for citation verification.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.verify import (
    verify_citation,
    CitationVerificationResult,
    Citation,
)


class MockVectorStore:
    def __init__(self):
        self.chunks = {}

    def add_chunk(self, chunk_id, text, metadata=None):
        self.chunks[chunk_id] = {
            "chunk_id": chunk_id,
            "text": text,
            "metadata": metadata or {},
        }

    def get_chunk(self, chunk_id):
        return self.chunks.get(chunk_id)

    def chunk_exists(self, chunk_id):
        return chunk_id in self.chunks


class TestChunkExistsCheck:
    def test_chunk_exists(self):
        vs = MockVectorStore()
        vs.add_chunk("chunk_1", "The OECD recommends transparency in AI systems.")
        result = verify_citation(
            chunk_id="chunk_1",
            claim_text="OECD recommends transparency",
            page_number=1,
            source_framework="OECD",
            vector_store=vs,
        )
        assert result.chunk_exists is True

    def test_chunk_does_not_exist(self):
        vs = MockVectorStore()
        result = verify_citation(
            chunk_id="nonexistent_chunk",
            claim_text="Some claim",
            page_number=1,
            source_framework="OECD",
            vector_store=vs,
        )
        assert result.passed is False
        assert result.chunk_exists is False
        assert "chunk_id does not exist" in (result.failure_reason or "")


class TestPageExistsCheck:
    def test_page_matches(self):
        vs = MockVectorStore()
        vs.add_chunk("chunk_a", "Text content", {"page_number": "5"})
        result = verify_citation(
            chunk_id="chunk_a",
            claim_text="Text content",
            page_number=5,
            source_framework="OECD",
            vector_store=vs,
        )
        assert result.page_exists is True

    def test_page_mismatch(self):
        vs = MockVectorStore()
        vs.add_chunk("chunk_b", "More text", {"page_number": "10"})
        result = verify_citation(
            chunk_id="chunk_b",
            claim_text="More text",
            page_number=3,
            source_framework="OECD",
            vector_store=vs,
        )
        assert result.passed is False

    def test_page_exceeds_document_length(self):
        vs = MockVectorStore()
        vs.add_chunk("chunk_c", "Some text", {"page_number": "2"})
        result = verify_citation(
            chunk_id="chunk_c",
            claim_text="Some text",
            page_number=50,
            source_framework="OECD",
            vector_store=vs,
            document_total_pages=10,
        )
        assert result.passed is False


class TestTextSupportsClaim:
    def test_text_directly_supports_claim(self):
        vs = MockVectorStore()
        vs.add_chunk(
            "chunk_d",
            "AI systems should be transparent and explainable to ensure accountability.",
        )
        result = verify_citation(
            chunk_id="chunk_d",
            claim_text="AI systems should be transparent and explainable",
            page_number=1,
            source_framework="OECD",
            vector_store=vs,
        )
        assert result.text_supports_claim is True

    def test_text_unrelated_to_claim(self):
        vs = MockVectorStore()
        vs.add_chunk(
            "chunk_e",
            "Climate change requires immediate action from all nations.",
        )
        result = verify_citation(
            chunk_id="chunk_e",
            claim_text="AI systems must be audited regularly",
            page_number=1,
            source_framework="OECD",
            vector_store=vs,
        )
        assert result.text_supports_claim is False
        assert result.passed is False

    def test_partial_support_insufficient_overlap(self):
        vs = MockVectorStore()
        vs.add_chunk(
            "chunk_f",
            "Privacy is important in digital systems.",
        )
        result = verify_citation(
            chunk_id="chunk_f",
            claim_text="AI systems require robust privacy frameworks with data protection impact assessments",
            page_number=1,
            source_framework="UNESCO",
            vector_store=vs,
        )
        assert result.text_supports_claim is False


class TestAllChecksPass:
    def test_all_checks_pass(self):
        vs = MockVectorStore()
        vs.add_chunk(
            "chunk_g",
            "UNESCO recommends that member states establish ethics committees for AI oversight.",
            {"page_number": "15", "framework": "UNESCO"},
        )
        result = verify_citation(
            chunk_id="chunk_g",
            claim_text="UNESCO recommends ethics committees for AI oversight",
            page_number=15,
            source_framework="UNESCO",
            vector_store=vs,
            document_total_pages=30,
        )
        assert result.passed is True
        assert result.chunk_exists is True
        assert result.page_exists is True
        assert result.text_supports_claim is True
