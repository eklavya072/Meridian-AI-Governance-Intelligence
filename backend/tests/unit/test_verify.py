"""
Unit tests for citation verification.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.verify import (
    Citation,
    CitationVerificationResult,
    verify_citation,
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

    def test_workspace_document_citation_exceeding_length_fails(self):
        """document_total_pages bounds a citation that genuinely comes FROM
        the uploaded workspace document (chunk carries a workspace_id) — the
        claimed page really can't exist in a document that short."""
        vs = MockVectorStore()
        vs.add_chunk(
            "chunk_own_doc",
            "Some text",
            {"page_number": "50", "workspace_id": "ws-123"},
        )
        result = verify_citation(
            chunk_id="chunk_own_doc",
            claim_text="Some text",
            page_number=50,
            source_framework="",
            vector_store=vs,
            document_total_pages=10,
        )
        assert result.page_exists is False
        assert "exceeds document length" in (result.failure_reason or "")

    def test_framework_citation_exceeding_uploaded_doc_length_still_passes(self):
        """Regression: a citation to a FRAMEWORK chunk (no workspace_id —
        shared corpus chunks are never workspace-scoped) must NOT be
        rejected against the unrelated uploaded document's page count. Real
        bug: a genuine page-89 citation into a 144-page framework was
        rejected as "exceeds document length" against a 20-36 page uploaded
        policy it has nothing to do with."""
        vs = MockVectorStore()
        vs.add_chunk(
            "chunk_framework",
            "Some text",
            {"page_number": "89", "framework": "EU AI Act"},
        )
        result = verify_citation(
            chunk_id="chunk_framework",
            claim_text="Some text",
            page_number=89,
            source_framework="EU AI Act",
            vector_store=vs,
            document_total_pages=20,
        )
        assert result.page_exists is True
        assert (
            result.failure_reason is None or "exceeds document length" not in result.failure_reason
        )


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


class TestCitationSeverity:
    """Fabricated and merely-unretrieved citations are different failures."""

    # Recitals are numbered "(70)" in the operative text, and PDF extraction
    # splits "Article" into "Ar ticle" throughout the EU AI Act — both are
    # exercised here so the classifier is not quietly matching on neither.
    DOCUMENT = (
        "Ar ticle 10 concerns data and data governance for high-r isk systems. "
        "(71) Having comprehensible information on how high-risk AI systems "
        "have been developed is essential to enable traceability."
    )
    RETRIEVED = "The provider shall keep records enabling traceability."

    def test_real_but_unretrieved_citation_is_unsupported_not_fabricated(self):
        from src.verify import classify_narrative_citations

        out = classify_narrative_citations(
            ["Article 10 requires examination for biases."],
            self.RETRIEVED,
            self.DOCUMENT,
        )
        assert out["unsupported"] == ["Article 10"]
        assert out["fabricated"] == []

    def test_ocr_split_headings_do_not_read_as_fabrication(self):
        """The document says "Ar ticle 10"; a naive check calls that invented."""
        from src.verify import classify_narrative_citations

        out = classify_narrative_citations(["Article 10 applies."], self.RETRIEVED, self.DOCUMENT)
        assert "Article 10" not in out["fabricated"]

    def test_recital_parenthesised_form_is_recognised(self):
        from src.verify import classify_narrative_citations

        out = classify_narrative_citations(
            ["Recital 71 underscores traceability."], self.RETRIEVED, self.DOCUMENT
        )
        assert out["unsupported"] == ["Recital 71"]

    def test_number_absent_from_the_document_is_fabricated(self):
        from src.verify import classify_narrative_citations

        out = classify_narrative_citations(
            ["Article 999 mandates carbon reporting."], self.RETRIEVED, self.DOCUMENT
        )
        assert out["fabricated"] == ["Article 999"]
        assert out["unsupported"] == []

    def test_without_a_document_nothing_is_called_invented(self):
        """No document to check against must not produce false accusations."""
        from src.verify import classify_narrative_citations

        out = classify_narrative_citations(["Article 10 applies."], self.RETRIEVED, "")
        assert out["fabricated"] == []
        assert out["unsupported"] == ["Article 10"]

    def test_citation_backed_by_retrieved_evidence_is_not_flagged(self):
        from src.verify import classify_narrative_citations

        out = classify_narrative_citations(
            ["Article 10 requires data governance."],
            "Article 10 requires data governance measures.",
            self.DOCUMENT,
        )
        assert out == {"fabricated": [], "unsupported": []}
