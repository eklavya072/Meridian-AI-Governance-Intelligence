import pytest

from src.deterministic import (
    DIMENSION_TOPIC_KEYWORDS,
    _chunk_matches_dimension,
    is_low_information_fragment,
)
from src.models import CoverageLevel


class TestKeywordBoundaries:
    def test_stem_keywords_do_not_match_unrelated_words(self):
        # False-positive spot checks: the stem entries must keep the same
        # boundary discipline as the earlier program/programming fix.
        from src.deterministic import NAMED_BODY_KEYWORDS, REPORTING_KEYWORDS, _has_keyword

        # "minister*" must not reach inside "administration"/"administrative"
        # (no word boundary before "minist").
        assert not _has_keyword("administration of the national AI plan", NAMED_BODY_KEYWORDS)
        assert not _has_keyword("administrative penalties apply", NAMED_BODY_KEYWORDS)
        # "indicatio*" must not match "indicator"/"indicative"/"indicating"
        # (stems diverge after "indicat") — a performance-indicator mention is
        # not a reporting duty.
        assert not _has_keyword("key performance indicators for AI", REPORTING_KEYWORDS)
        assert not _has_keyword("the results are indicative of progress", REPORTING_KEYWORDS)
        assert not _has_keyword("indicating that the system is stable", REPORTING_KEYWORDS)
        # "notif*" only matches the notification family — "notional" and
        # "notify" (already a literal) are the closest neighbours.
        assert not _has_keyword("a notional budget allocation", REPORTING_KEYWORDS)


class TestMechanismLanguage:
    """A passage imposing a requirement in the policy's own words is a
    mechanism; a bare principle is not. Used to keep definitions and
    principles out of auto-attached citations."""

    def test_text_contains_mechanism(self):
        from src.deterministic import text_contains_mechanism

        assert (
            text_contains_mechanism("The Ministry shall publish an annual transparency report")
            is True
        )
        assert (
            text_contains_mechanism("AI operators must ensure safe deployment of high-risk systems")
            is True
        )
        assert text_contains_mechanism("The policy recognizes the importance of fairness") is False


class TestDimensionGrounding:
    """Regression: the exact false-positive case that shipped two wrong
    Covered verdicts on the Singapore NAIS run.

    A UN-advisory-body participation paragraph (retrieved for
    Accountability) and an events-calendar paragraph (retrieved for
    Inclusivity) both matched R1/R2 on commitment vocabulary alone
    ("will support", "program", "intends to") with no check that the
    content was actually about the dimension. All three fixes together
    (word boundaries + named-body co-occurrence + dimension grounding)
    must keep these chunks inert, while a genuinely on-topic chunk with a
    named body and commitment language still fires.
    """

    UN_ADVISORY_CHUNK = {
        "chunk_id": "c1",
        "text": (
            "We participate actively in international discourse on AI governance "
            "to raise capacity, share best practices, and shape rules around AI. "
            "The UN High-Level Advisory Body on AI (HLAB), announced by the UN "
            "Secretary-General, comprises 39 experts from across UN Member "
            "States, and it will support the international community's efforts "
            "to govern AI."
        ),
    }

    EVENTS_CALENDAR_CHUNK = {
        "chunk_id": "c2",
        "text": (
            "Participants emphasised the need to nurture a strong, tight-knit "
            "AI community in Singapore. The site will be supported by a full "
            "calendar of AI-related programming, including community-run events "
            "such as hackathons, demo days and guest lectures. Singapore "
            "intends to provide more platforms which can bring the AI community "
            "together."
        ),
    }

    # The other residual off-topic match found during manual re-verification
    # of the Singapore run: a talent/community-ecosystem passage (page 42)
    # that grounds on the bare word "participation" and contains "intends
    # to"/"will create". It is about AI talent attraction, NOT inclusivity
    # governance (accessibility, non-discrimination, digital divide) — bare
    # "participation" is deliberately NOT in the Inclusivity topic keywords,
    # so this chunk must stay inert.
    TALENT_ECOSYSTEM_CHUNK = {
        "chunk_id": "c4",
        "text": (
            "The opportunity to spar and collaborate with like-minded peers can "
            "enrich these ideas and accelerate the translation into products "
            "and new value. Such synergies are seen in global AI hubs such as "
            "San Francisco, where stakeholders working across all parts of the "
            "AI ecosystem are found in close proximity, and the vibrancy of the "
            "community in turn attracts the participation of even more talented "
            "individuals, companies, and capital. To realise similar benefits, "
            "Singapore intends to provide more platforms which can bring our AI "
            "community together. We want to engage with more of our talent pool, "
            "and connect them to global AI experts for greater opportunities to "
            "interact and collaborate. Over time, we hope these connections will "
            "create a sense of identity and fraternity."
        ),
    }

    def test_un_advisory_chunk_not_topically_accountability(self):
        # Dimension grounding: the chunk is about international participation,
        # not accountability governance.
        assert not _chunk_matches_dimension(self.UN_ADVISORY_CHUNK["text"], "Accountability")

    def test_events_calendar_chunk_not_topically_inclusivity(self):
        # Dimension grounding: the chunk is about community/talent building,
        # not inclusivity governance.
        assert not _chunk_matches_dimension(self.EVENTS_CALENDAR_CHUNK["text"], "Inclusivity")


class TestSubstantiveSpecificityGate:
    """Anti-false-positive: the broad evidence pool fixed the false-Missing
    class, but the loose relevance gate (0.42) also admits PROCEDURAL
    authority provisions — "the Minister may approve/support AI data
    centres", "shall promote measures to facilitate the production,
    collection, management, distribution, utilization of learning data" —
    which contain obligation language + a named body yet impose no
    dimension-specific governance requirement. These must NOT fire R1/R2:
    procedural authority ≠ substantive governance mechanism. The pipeline
    supplies a substantive_match_fn (semantic closeness of the chunk's
    mechanism sentences to the dimension's profile); when provided, a chunk
    must pass BOTH gates to fire the ladder."""

    # The exact Korea Env Sustainability pool passage that (incorrectly)
    # fired R1+R2 in the re-run: a procedural learning-data facilitation
    # duty, not an environmental governance mechanism.
    KOREA_ENV_PROCEDURAL = {
        "chunk_id": "c-kr-env",
        "text": (
            "The Minister of Science and ICT shall, in consultation with the "
            "heads of relevant central administrative agencies, promote "
            "necessary measures to facilitate the production, collection, "
            "management, distribution, utilization of Learning Data."
        ),
    }

    # The Korea Privacy pool passage: public-institution decision-making
    # procedures, not a privacy mechanism.
    KOREA_PRIV_PROCEDURAL = {
        "chunk_id": "c-kr-priv",
        "text": (
            "Decision-making by the national and local governments, and public "
            "institutions pursuant to Article 4 of the Act on the Operation of "
            "Public Institutions that use AI shall follow the procedures "
            "prescribed by Presidential Decree."
        ),
    }

    # ── Sentence-level evidence discipline (R2 co-location leak) ─────────
    # The substantive gate validates ANY mechanism-bearing sentence of a
    # chunk, so R2 used to be able to fire using a strong phrase / named
    # body located in a DIFFERENT sentence than the one that passed the
    # gate — a mixed Article 32/33 chunk promoted Fairness on a safety
    # provision. R2 must now require the SAME sentence that carries the
    # strong phrase + named body to itself pass the substantive gate.
    MIXED_ENV_CHUNK = {
        "chunk_id": "c-mixed",
        "text": (
            "AI data centres shall report their annual energy consumption "
            "and carbon emissions. "
            "The Minister of Science and ICT shall establish a national AI "
            "research institute programme under the Ministry of Science."
        ),
    }

    def test_all_dimensions_have_topic_keywords(self):
        for dim in (
            "Transparency",
            "Accountability",
            "Privacy",
            "Safety",
            "Human Autonomy",
            "Inclusivity",
            "Fairness",
            "Environmental Sustainability",
        ):
            assert DIMENSION_TOPIC_KEYWORDS.get(dim), dim


class TestLowInformationFragment:
    """Glossary/index fragments (a term + footnote number, or a bare heading)
    carry no real sentence content and must be deprioritised over substantive
    chunks — the exact artifacts observed in live evidence ("Explainability15",
    "Transparency27", "Accountability 6")."""

    def test_glossary_term_plus_number(self):
        assert is_low_information_fragment("Explainability15") is True
        assert is_low_information_fragment("Transparency27") is True
        assert is_low_information_fragment("Accountability 6") is True
        assert is_low_information_fragment("Data privacy 12, 45") is True

    def test_short_heading_fragments(self):
        assert is_low_information_fragment("AI Ethics Board") is True
        assert is_low_information_fragment("Chapter 5") is True
        assert is_low_information_fragment("") is True
        assert is_low_information_fragment(None) is True

    def test_real_sentences_pass(self):
        assert (
            is_low_information_fragment(
                "The policy establishes a National AI Ethics Board with a "
                "human-in-the-loop review mandate for high-impact deployments."
            )
            is False
        )
        assert (
            is_low_information_fragment(
                "The government will ensure algorithmic transparency in public services."
            )
            is False
        )
        assert (
            is_low_information_fragment("Published in 2024, the framework sets out obligations.")
            is False
        )
        assert is_low_information_fragment("The policy establishes an ethics board.") is False
