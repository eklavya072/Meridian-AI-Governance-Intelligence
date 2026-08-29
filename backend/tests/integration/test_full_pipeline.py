"""
Integration test: full pipeline end-to-end with a real small test document.

This test requires:
- ChromaDB (persistent, local)
- sentence-transformers (BAAI/bge-small-en-v1.5)
- A configured LLM provider (Gemini or Groq), or a mock
"""

import pytest
import os
import tempfile
from pathlib import Path

from src.ingestion import ingest_document
from src.vectorstore import VectorStore
from src.gap_analyzer import GapAnalyzer, GOVERNANCE_DIMENSIONS
from src.brief_generator import generate_executive_brief_text

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION_TESTS"),
    reason="Set RUN_INTEGRATION_TESTS=1 to run integration tests",
)


@pytest.fixture
def sample_pdf():
    from pypdf import PdfWriter
    import io

    writer = PdfWriter()
    page = writer.add_blank_page(200, 200)

    text_content = """
    National AI Strategy - Test Document

    1. Introduction
    This nation is committed to developing artificial intelligence in a responsible manner.

    2. Transparency
    We will ensure AI systems are transparent and explainable to users.

    3. Accountability
    Clear accountability mechanisms will be established for AI deployment.

    4. Privacy
    Data protection and privacy will be prioritized in all AI systems.

    5. Human Oversight
    Humans will maintain meaningful control over AI decision-making.

    6. Inclusion
    AI benefits must be accessible to all segments of society.

    7. Governance
    A national AI governance framework will be established.

    8. Risk Management
    Risk assessment procedures will be implemented for high-risk AI.

    9. Ethics
    Ethical principles will guide all AI development and deployment.
    """.strip()

    from io import BytesIO
    packet = BytesIO()
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(packet)
    y = 750
    for line in text_content.split("\n"):
        c.drawString(50, y, line.strip())
        y -= 15
    c.save()
    packet.seek(0)

    from pypdf import PdfReader
    overlay = PdfReader(packet)
    page.merge_page(overlay.pages[0])

    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    return buf.getvalue()


@pytest.fixture
def temp_pdf_file(sample_pdf):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(sample_pdf)
        return Path(f.name)


@pytest.fixture
def vector_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        vs = VectorStore(persist_dir=tmpdir)
        yield vs


class TestFullPipeline:
    def test_ingest_to_retrieve(self, vector_store, temp_pdf_file):
        chunks = ingest_document(temp_pdf_file, framework_name="Test Framework")
        assert len(chunks) > 0

        vector_store.add_chunks(chunks)
        count = vector_store.count_chunks()
        assert count == len(chunks)

        results = vector_store.retrieve("What does this document say about transparency?", top_k=3)
        assert len(results) > 0
        assert any("transparency" in r["text"].lower() for r in results)

    def test_ingest_analyze_brief(self, vector_store, temp_pdf_file):
        chunks = ingest_document(temp_pdf_file, framework_name="Test Framework")
        vector_store.add_chunks(chunks)

        full_text = "\n".join(c.text for c in chunks)
        analyzer = GapAnalyzer(vector_store=vector_store)
        result = analyzer.analyze(
            document_text=full_text,
            document_name="test_doc.pdf",
            workspace_id="test-ws-001",
            frameworks=["Test Framework"],
        )

        assert result.analysis_id is not None
        assert len(result.governance_gaps) == len(GOVERNANCE_DIMENSIONS)
        assert result.total_retrieved > 0

        brief = generate_executive_brief_text(result)
        assert "EXECUTIVE BRIEF" in brief
        assert "EXECUTIVE SUMMARY" in brief
        assert "KEY FINDINGS" in brief
        assert "RECOMMENDATIONS" in brief
        assert "REFERENCES" in brief

    def test_all_dimensions_checked(self, vector_store, temp_pdf_file):
        chunks = ingest_document(temp_pdf_file, framework_name="Test Framework")
        vector_store.add_chunks(chunks)

        full_text = "\n".join(c.text for c in chunks)
        analyzer = GapAnalyzer(vector_store=vector_store)
        result = analyzer.analyze(
            document_text=full_text,
            document_name="test_doc.pdf",
            workspace_id="test-ws-002",
            frameworks=["Test Framework"],
        )

        dimensions_found = {g.dimension for g in result.governance_gaps}
        for dim in GOVERNANCE_DIMENSIONS:
            assert dim in dimensions_found, f"Dimension {dim} missing from analysis"
