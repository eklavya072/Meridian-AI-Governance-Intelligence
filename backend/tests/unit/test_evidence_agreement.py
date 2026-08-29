import pytest

from src.evidence_agreement import (
    _contains_negation,
    _has_contradictory_phrasing,
    analyze_evidence_agreement,
    compute_evidence_agreement_score,
)
from src.models import EvidenceAgreement, EvidenceItem


def test_contains_negation():
    assert _contains_negation("the policy does not address transparency")
    assert _contains_negation("there is a lack of oversight")
    assert not _contains_negation("the policy addresses transparency")
    assert not _contains_negation("")


def test_contradictory_phrasing():
    assert _has_contradictory_phrasing(
        "the policy addresses transparency",
        "the policy does not address transparency",
    )
    assert not _has_contradictory_phrasing(
        "the policy addresses transparency",
        "the policy also addresses accountability",
    )


def test_evidence_agreement_empty():
    assert analyze_evidence_agreement([]) == []


def test_evidence_agreement_single():
    item = EvidenceItem(chunk_id="c1", text="test", source_framework="fw")
    assert analyze_evidence_agreement([item]) == []


def test_evidence_agreement_duplicate():
    a = EvidenceItem(
        chunk_id="c1", text="exact duplicate text", source_framework="fw1", is_document=True
    )
    b = EvidenceItem(
        chunk_id="c2", text="exact duplicate text", source_framework="fw1", is_document=True
    )
    pairs = analyze_evidence_agreement([a, b])
    assert len(pairs) == 1
    assert pairs[0].agreement == EvidenceAgreement.DUPLICATE


def test_evidence_agreement_short_texts():
    a = EvidenceItem(chunk_id="c1", text="a" * 50, source_framework="fw1")
    b = EvidenceItem(chunk_id="c2", text="b" * 50, source_framework="fw2")
    pairs = analyze_evidence_agreement([a, b])
    assert len(pairs) == 1


def test_compute_agreement_score_no_pairs():
    assert compute_evidence_agreement_score([]) == 1.0


def test_compute_agreement_score_supporting():
    from src.evidence_agreement import EvidenceAgreement, EvidencePair

    pairs = [
        EvidencePair(
            item_a_id="a", item_b_id="b", agreement=EvidenceAgreement.SUPPORTING, score=0.85
        ),
        EvidencePair(
            item_a_id="a", item_b_id="c", agreement=EvidenceAgreement.SUPPORTING, score=0.75
        ),
    ]
    score = compute_evidence_agreement_score(pairs)
    assert 0 < score <= 1.0


def test_compute_agreement_score_conflicting():
    from src.evidence_agreement import EvidenceAgreement, EvidencePair

    pairs = [
        EvidencePair(
            item_a_id="a", item_b_id="b", agreement=EvidenceAgreement.CONFLICTING, score=0.8
        ),
    ]
    score = compute_evidence_agreement_score(pairs)
    assert 0 <= score <= 1.0
