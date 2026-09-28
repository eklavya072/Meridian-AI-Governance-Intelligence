"""Negation is matched as whole words, not substrings."""

import pytest

from src.evidence_agreement import _contains_negation


@pytest.mark.parametrize(
    "text",
    [
        "Providers shall notify the authority and know their obligations.",
        "Normative frameworks set out annual notices.",
        "The board shall publish an annual report.",
    ],
)
def test_words_that_merely_contain_a_negator_are_not_negated(text):
    assert not _contains_negation(text)


@pytest.mark.parametrize(
    "text",
    [
        "The Act does not establish an oversight body.",
        "No provider shall deploy such a system.",
        "Neither the ministry nor the regulator is named.",
        "The policy lacks any redress mechanism.",
        "Operators can’t rely on this exemption.",
    ],
)
def test_real_negation_is_found(text):
    assert _contains_negation(text)
