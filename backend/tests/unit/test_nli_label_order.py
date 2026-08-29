"""Regression tests for two silent bugs in the NLI verification path.

Both were found by running the path against 403 real stored citations
rather than by reading it. Neither raised, neither logged, and both
produced numbers that looked like plausible scores:

1. The label order was assumed positionally as
   [entailment, neutral, contradiction]. cross-encoder/nli-deberta-v3-base
   reports {0: contradiction, 1: entailment, 2: neutral}, so the code read
   contradiction as entailment and neutral as contradiction.
2. CrossEncoder.predict returns LOGITS for a multi-class head, roughly -6
   to +6, which were compared directly against 0.6 / 0.4 probability
   thresholds. A logit of 5.8 for `neutral` cleared the contradiction bar
   by being a large number.

Together they labelled 362 of 403 citations "contradicts" — on a set where
85.4% of the quoted excerpts are literally inside the chunk they cite.
"""

import src.nli_verifier as nli_mod
from src.models import VerificationStatus
from src.nli_verifier import NLIVerifier, _resolve_label_index, _softmax


class _Config:
    def __init__(self, id2label):
        self.id2label = id2label


class _FakeCrossEncoder:
    """Deberta's real label order, and raw logits like the real model returns."""

    def __init__(self, logits):
        self.config = _Config({0: "contradiction", 1: "entailment", 2: "neutral"})
        self._logits = logits

    def predict(self, pairs):
        return [self._logits]


def _verifier_with(logits, monkeypatch):
    monkeypatch.setattr(nli_mod, "ENABLE_NLI_VERIFICATION", True)
    v = NLIVerifier()
    v._model = _FakeCrossEncoder(logits)
    v._label_index = _resolve_label_index(v._model)
    v._load_attempted = True
    return v


def test_label_index_read_from_the_checkpoint_not_assumed():
    idx = _resolve_label_index(_FakeCrossEncoder([0, 0, 0]))

    assert idx == {"contradiction": 0, "entailment": 1, "neutral": 2}


def test_label_index_falls_back_when_unreadable():
    class _NoConfig:
        pass

    assert _resolve_label_index(_NoConfig()) == {
        "entailment": 0,
        "neutral": 1,
        "contradiction": 2,
    }


def test_softmax_turns_logits_into_a_distribution():
    probs = _softmax([-1.49, -3.89, 5.84])

    assert abs(sum(probs) - 1.0) < 1e-9
    assert probs[2] > 0.99
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_high_entailment_logit_reads_as_supports(monkeypatch):
    # index 1 is entailment for this checkpoint
    v = _verifier_with([-2.0, 6.0, -1.0], monkeypatch)

    result = v.verify("providers shall keep logs", "Article 12 requires automatic logging.")

    assert result.status == VerificationStatus.SUPPORTS
    assert result.confidence > 0.9


def test_high_contradiction_logit_reads_as_contradicts(monkeypatch):
    # index 0 is contradiction. Under the old positional read this was
    # entailment, so a contradicted claim passed verification.
    v = _verifier_with([6.0, -2.0, -1.0], monkeypatch)

    result = v.verify("the Act bans logging", "Article 12 requires automatic logging.")

    assert result.status == VerificationStatus.CONTRADICTS


def test_dominant_neutral_is_not_reported_as_contradiction(monkeypatch):
    # The exact shape that produced 362 false "contradicts": neutral wins,
    # and its logit is large. Neutral means "no entailment either way", so
    # the only honest answer is irrelevant, never contradicts.
    v = _verifier_with([-1.49, -3.89, 5.84], monkeypatch)

    result = v.verify("some claim", "some passage")

    assert result.status == VerificationStatus.IRRELEVANT
    assert result.status != VerificationStatus.CONTRADICTS


def test_confidence_is_a_probability(monkeypatch):
    v = _verifier_with([-1.49, -3.89, 5.84], monkeypatch)

    result = v.verify("some claim", "some passage")

    # Previously this carried a raw logit, so a "confidence" of 5.84 could
    # be rendered to a reader as a score.
    assert 0.0 <= result.confidence <= 1.0
