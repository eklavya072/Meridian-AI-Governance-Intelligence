"""The verdict is computed once per dimension, and read back everywhere else.

Every contradiction found in QA so far has the same shape: two pieces of code
answering the same question about the same document, drifting apart because a
fix landed on one of them.

    coverage      computed pre-LLM WITH the mechanism gate, and again
                  post-LLM WITHOUT it -> a soft-law guideline shipped
                  "Covered" for Privacy above "Provides 1 of 7 governance
                  mechanisms ... Not addressed: consent, data minimisation".
                  The prompt said Partial. The stored verdict said Covered.

    maturity      coverage's force bar was corrected; maturity kept its own
                  copy of the old degenerate threshold -> "Partial ... stands
                  alone rather than forming a developed regime" reported
                  alongside "Operationalized".

    reason_flagged  the reconciliation that stops a Covered verdict shipping
                  under "lacks..." prose sat behind a flag the winning code
                  path clears, so it only ever ran on the fallback path.

These are not three bugs. They are one bug three times, and it recurs for as
long as duplicate computations are allowed to exist. This module fails the
build when a second call site appears.
"""
import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "gap_analyzer.py"

# Each of these decides part of the verdict. _compute_deterministic_verdict
# calls them once, before the LLM call, and stores the result in `determined`.
# Anything downstream must read `determined`, never recompute.
SINGLE_CALL_ONLY = {
    "coverage_from_profile": 1,
    "maturity_from_profile": 1,
    "detect_mechanisms": 1,
    "build_profile": 1,
    "retrieve_scoring_pool": 1,
}


def _call_sites(tree):
    counts: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id if isinstance(func, ast.Name)
            else func.attr if isinstance(func, ast.Attribute)
            else None
        )
        if name:
            counts[name] = counts.get(name, 0) + 1
    return counts


@pytest.mark.parametrize("func,expected", sorted(SINGLE_CALL_ONLY.items()))
def test_verdict_inputs_have_exactly_one_call_site(func, expected):
    counts = _call_sites(ast.parse(SRC.read_text()))
    actual = counts.get(func, 0)
    assert actual == expected, (
        f"{func}() has {actual} call sites in gap_analyzer.py, expected "
        f"{expected}.\n\n"
        "The verdict is computed once, in _compute_deterministic_verdict, and "
        "handed to the model as an input. If you need this value later, read "
        "it from the `determined` dict — do not call it again. A second call "
        "site is a second answer to the same question, and the two WILL drift: "
        "that is exactly how Covered/1-of-7-mechanisms and "
        "Partial/Operationalized both shipped."
    )


def test_determined_dict_exposes_everything_downstream_needs():
    """The read-back path only works if the verdict actually carries these."""
    from src.gap_analyzer import GapAnalyzer  # noqa: F401
    source = SRC.read_text()
    start = source.index("def _compute_deterministic_verdict")
    end = source.index("def _analyze_dimension_combined")
    returned = source[start:end]
    for key in (
        "profile", "scoring_pool", "coverage_label", "coverage_note",
        "maturity_label", "maturity_note", "mechanisms",
    ):
        assert f'"{key}"' in returned, (
            f"_compute_deterministic_verdict must return '{key}' — downstream "
            "code reads it instead of recomputing."
        )


class TestCoveredNeverShipsUnderGapProse:
    """A Covered verdict and "the document lacks X" cannot both be true.

    Live output, Nigeria and Kenya, Inclusivity, both marked Covered:
      "...but lacks technical mechanisms for algorithmic bias testing,
       accessibility standards, or demographic fairness monitoring."
    """

    def test_real_shipped_contradictions_are_detected(self):
        from src.consistency import (
            detect_ladder_raise_contradiction,
            LADDER_RAISE_REVIEW_THRESHOLD,
        )
        for text in (
            "The strategy highlights principles of inclusion, diversity, and "
            "non-discrimination and commits to a foresight study on vulnerable "
            "groups, but lacks technical mechanisms for algorithmic bias "
            "testing, accessibility standards, or demographic fairness monitoring.",
            "The strategy acknowledges inclusivity and social inclusion in "
            "principle but lacks concrete operational mechanisms such as "
            "mandatory bias testing, accessibility requirements, or formal "
            "participatory channels for underrepresented groups.",
        ):
            score, phrases = detect_ladder_raise_contradiction(text)
            assert score >= LADDER_RAISE_REVIEW_THRESHOLD, phrases

    def test_clean_covered_prose_is_left_alone(self):
        """The reconciliation must not rewrite text that says nothing wrong."""
        from src.consistency import (
            detect_ladder_raise_contradiction,
            LADDER_RAISE_REVIEW_THRESHOLD,
        )
        score, _ = detect_ladder_raise_contradiction(
            "The regulation establishes comprehensive obligations across the "
            "AI lifecycle, backed by market surveillance authorities."
        )
        assert score < LADDER_RAISE_REVIEW_THRESHOLD

    def test_reconciliation_is_not_gated_on_coverage_rules(self):
        """It used to sit inside `if coverage_rules:`, which the winning path
        clears — so the guard existed but never ran on a real verdict."""
        source = SRC.read_text()
        block = source[source.index("Covered verdicts never ship under gap prose"):]
        block = block[: block.index("gap_detected = coverage")]
        # Comments in this block explain the old gating on purpose, so strip
        # them: the assertion is about what executes, not what is documented.
        code = "\n".join(
            line for line in block.splitlines()
            if not line.lstrip().startswith("#")
        )
        assert "coverage_rules" not in code, (
            "The Covered/reason_flagged reconciliation must not depend on "
            "coverage_rules — the evidence-profile path clears it before "
            "reaching here, which is how the contradiction shipped."
        )


class TestLadderIsFallbackOnly:
    """The ladder's machinery must not be built when the profile supersedes it.

    Per dimension the ladder needs a multi-query RRF sweep of the whole
    document, a batched embedding call, and two sentence-level semantic
    predicates. On every real document the evidence profile wins and all of
    that was discarded — eight times per run.
    """

    def _guarded_block(self):
        source = SRC.read_text()
        start = source.index("use_profile_verdict = bool(")
        end = source.index("raw_coverage = coverage", start)
        return source[start:end]

    def test_evidence_pool_is_skipped_when_the_profile_wins(self):
        block = self._guarded_block()
        pool_at = block.index("retrieve_document_evidence_pool")
        guard_at = block.index("not use_profile_verdict")
        assert guard_at < pool_at, (
            "retrieve_document_evidence_pool must sit behind the "
            "`not use_profile_verdict` guard — its result feeds only the "
            "ladder, which the evidence profile supersedes."
        )

    def test_semantic_predicates_are_skipped_when_the_profile_wins(self):
        block = self._guarded_block()
        for name in (
            "_batch_prewarm_sentence_cache",
            "_build_dimension_relevance_predicate",
            "_build_dimension_substantive_predicate",
        ):
            assert name in block
        assert block.count("not use_profile_verdict") >= 2, (
            "Both the evidence pool and the predicate builders need the guard."
        )

    def test_ladder_call_is_guarded(self):
        source = SRC.read_text()
        idx = source.index("validated_coverage, coverage_rules = validate_coverage_deterministic(")
        preceding = source[:idx].rsplit("\n", 4)[-4:]
        assert any("not use_profile_verdict" in line for line in preceding), (
            "validate_coverage_deterministic must only run on the fallback "
            "path; its verdict is otherwise computed and thrown away."
        )

    def test_predicates_default_to_none_so_the_fallback_stays_safe(self):
        """Skipping construction must leave the names defined, not undefined."""
        block = self._guarded_block()
        assert "dim_match = None" in block
        assert "subst_match = None" in block
