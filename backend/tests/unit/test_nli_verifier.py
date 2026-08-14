import pytest
from src.nli_verifier import NLIVerifier
from src.models import VerificationStatus


def test_nli_verifier_init():
    verifier = NLIVerifier()
    assert not verifier.is_available


def test_nli_verifier_empty_claim():
    verifier = NLIVerifier(embed_function=lambda x: [0.5] * 384)
    result = verifier.verify("", "Some chunk text", "c1")
    assert result.status == VerificationStatus.IRRELEVANT
    assert result.confidence == 0.0


def test_nli_verifier_empty_chunk():
    verifier = NLIVerifier(embed_function=lambda x: [0.5] * 384)
    result = verifier.verify("A claim", "", "c1")
    assert result.status == VerificationStatus.IRRELEVANT


def test_nli_verifier_fallback_to_embedding():
    embed_calls = []

    def mock_embed(text):
        embed_calls.append(text)
        if "claim" in text:
            return [1.0, 0.0, 0.0]
        return [0.9, 0.1, 0.0]

    verifier = NLIVerifier(embed_function=mock_embed)
    result = verifier.verify("test claim about AI",
                             "test document about artificial intelligence",
                             "c1")
    assert result.status in (VerificationStatus.SUPPORTS,
                             VerificationStatus.PARTIALLY_SUPPORTS)
    assert len(embed_calls) > 0


def test_nli_verifier_irrelevant_text():
    embed_calls = []

    def mock_embed(text):
        embed_calls.append(text)
        if "claim" in text:
            return [1.0, 0.0, 0.0]
        return [0.0, 0.0, 1.0]

    verifier = NLIVerifier(embed_function=mock_embed)
    result = verifier.verify("privacy claim about data protection",
                             "weather report for Monday",
                             "c1")
    assert result.confidence < 0.5


def test_nli_verifier_method_string():
    embed_calls = []

    def mock_embed(text):
        embed_calls.append(text[:50])
        if "claim" in text.lower():
            return [1.0, 0.0]
        return [0.8, 0.2]

    verifier = NLIVerifier(embed_function=mock_embed)
    result = verifier.verify("test claim", "test chunk", "c1")
    assert result.method in ("embedding_similarity", "keyword_only")


def test_verify_citation_nli_function():
    from src.nli_verifier import verify_citation_nli
    result = verify_citation_nli("test claim", "test chunk")
    assert result.chunk_id == ""
    assert result.claim == "test claim"
