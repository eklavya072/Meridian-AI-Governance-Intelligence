import pytest

from src.evidence import EvidenceGraphBuilder
from src.models import EvidenceGraph


def test_evidence_graph_builder_init():
    builder = EvidenceGraphBuilder(lambda x: [0.5] * 384)
    assert builder._embed is not None
    assert builder._profiles == {}


def test_evidence_graph_empty_chunks():
    builder = EvidenceGraphBuilder(lambda x: [0.5] * 384)
    builder.set_dimension_profiles(
        {
            "Transparency": {
                "definition": "test",
                "aspects": ["Aspect 1", "Aspect 2"],
                "is_core": True,
            }
        }
    )
    graph = builder.build_graph("Transparency", [], [])
    assert isinstance(graph, EvidenceGraph)
    assert graph.dimension == "Transparency"
    assert graph.total_chunks_retrieved == 0
    assert len(graph.missing_aspects) == 2


def test_evidence_graph_with_document_chunks():
    builder = EvidenceGraphBuilder(lambda x: [0.5] * 384)
    builder.set_dimension_profiles(
        {
            "Transparency": {
                "definition": "test",
                "aspects": ["disclosure", "explainability"],
                "is_core": True,
            }
        }
    )
    doc_chunks = [
        {
            "chunk_id": "c1",
            "text": "the system discloses all relevant information to users",
            "source_framework": "doc",
            "page_number": 1,
        },
    ]
    graph = builder.build_graph("Transparency", doc_chunks, [])
    assert graph.total_chunks_retrieved == 1
    assert 0 <= graph.evidence_quality_score <= 1.0


def test_evidence_graph_deduplication():
    builder = EvidenceGraphBuilder(lambda x: [1.0, 0.0, 0.0] if len(x) > 10 else [0.0, 1.0, 0.0])
    builder.set_dimension_profiles(
        {
            "TestDim": {
                "definition": "test definition that is long enough to pass the min length filter",
                "aspects": ["Aspect A", "Aspect B"],
                "is_core": True,
            }
        }
    )
    chunks = [
        {
            "chunk_id": "c1",
            "text": "identical text that is long enough to pass the min length filter for sure now",
            "source_framework": "doc1",
        },
        {
            "chunk_id": "c2",
            "text": "identical text that is long enough to pass the min length filter for sure now",
            "source_framework": "doc2",
        },
    ]
    graph = builder.build_graph("TestDim", chunks, [])
    assert graph.total_chunks_retrieved == 2
    assert graph.redundancy_ratio > 0.0


def test_evidence_graph_quality_factors():
    builder = EvidenceGraphBuilder(lambda x: [0.5] * 384)
    builder.set_dimension_profiles(
        {
            "TestDim": {
                "definition": "test definition",
                "aspects": ["Aspect A", "Aspect B", "Aspect C"],
                "is_core": True,
            }
        }
    )
    doc_chunks = [
        {"chunk_id": "c1", "text": "A" * 200, "source_framework": "doc1", "similarity_score": 0.9},
        {"chunk_id": "c2", "text": "B" * 200, "source_framework": "doc2", "similarity_score": 0.8},
    ]
    fw_chunks = [
        {"chunk_id": "c3", "text": "C" * 200, "source_framework": "fw1", "similarity_score": 0.7},
    ]
    graph = builder.build_graph("TestDim", doc_chunks, fw_chunks)
    assert graph.evidence_quality_score > 0.0
    assert len(graph.quality_factors) >= 3


def test_evidence_graph_source_diversity():
    builder = EvidenceGraphBuilder(lambda x: [0.5] * 384)
    builder.set_dimension_profiles(
        {
            "TestDim": {
                "definition": "test definition that is sufficiently long for the min length check to pass easily",
                "aspects": ["Aspect"],
                "is_core": False,
            }
        }
    )
    chunks = [
        {
            "chunk_id": "c1",
            "text": "detailed policy analysis text that discusses transparency requirements for AI governance frameworks across multiple jurisdictions and sectors and is definitely long enough",
            "source_framework": "doc1",
        },
        {
            "chunk_id": "c2",
            "text": "detailed policy analysis text that discusses accountability standards for AI governance frameworks across multiple jurisdictions and sectors and is definitely long enough",
            "source_framework": "doc2",
        },
        {
            "chunk_id": "c3",
            "text": "detailed policy analysis text that discusses fairness guidelines for AI governance frameworks across multiple jurisdictions and sectors and is definitely long enough",
            "source_framework": "fw1",
        },
    ]
    graph = builder.build_graph("TestDim", chunks, [])
    assert graph.source_diversity_score > 0.0


def test_evidence_graph_min_text_length():
    builder = EvidenceGraphBuilder(lambda x: [0.5] * 384)
    builder.set_dimension_profiles(
        {
            "TestDim": {
                "definition": "test",
                "aspects": ["Aspect"],
                "is_core": False,
            }
        }
    )
    chunks = [
        {"chunk_id": "c1", "text": "short", "source_framework": "doc1"},
    ]
    graph = builder.build_graph("TestDim", chunks, [])
    assert graph.total_chunks_retrieved == 0


def test_evidence_graph_reranker_score_priority():
    builder = EvidenceGraphBuilder(lambda x: [0.5] * 384)
    builder.set_dimension_profiles(
        {
            "TestDim": {
                "definition": "test",
                "aspects": ["Aspect"],
                "is_core": False,
            }
        }
    )
    chunks = [
        {
            "chunk_id": "c1",
            "text": "detailed text for analysis of something important",
            "source_framework": "doc1",
            "reranker_score": 0.95,
            "rrf_score": 0.5,
        },
    ]
    graph = builder.build_graph("TestDim", chunks, [])
    assert graph.evidence_quality_score > 0.0
