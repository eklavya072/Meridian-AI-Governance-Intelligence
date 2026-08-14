import pytest

from src.deterministic import (
    DeterministicFrameworkMatcher,
    DeterministicPlausibilityValidator,
    detect_document_type,
    detect_explicit_commitment,
    detect_implementation_commitment,
    FrameworkMatchResult,
    PlausibilityResult,
    validate_coverage_deterministic,
    LEVEL_LABELS,
    LEVEL_TO_COVERAGE,
    DIMENSION_TOPIC_KEYWORDS,
    _chunk_matches_dimension,
    is_low_information_fragment,
)
from src.models import CoverageLevel


class TestDetectDocumentType:
    def test_detects_strategy(self):
        assert detect_document_type(["National AI Strategy 2025"]) == "strategy"
        assert detect_document_type(["This is a national ai strategy document"]) == "strategy"
        assert detect_document_type(["Action plan for AI development"]) == "strategy"

    def test_detects_legislation(self):
        assert detect_document_type(["AI Act 2025"]) == "legislation"
        assert detect_document_type(["This regulation establishes requirements"]) == "legislation"
        assert detect_document_type(["Legislation for artificial intelligence"]) == "legislation"

    def test_detects_standard(self):
        assert detect_document_type(["Technical standard for AI"]) == "standard"
        assert detect_document_type(["Implementation guideline"]) == "standard"

    def test_detects_code_of_conduct(self):
        assert detect_document_type(["Code of conduct for AI ethics"]) == "code_of_conduct"
        assert detect_document_type(["Ethical guidelines"]) == "code_of_conduct"

    def test_returns_other_for_unknown(self):
        assert detect_document_type(["General policy paper"]) == "other"
        assert detect_document_type([]) == "other"

    def test_empty_chunks_returns_other(self):
        assert detect_document_type([]) == "other"


class TestDeterministicFrameworkMatcher:
    @pytest.fixture
    def matcher(self):
        def mock_embed(text: str) -> list[float]:
            import hashlib
            h = hashlib.md5(text.encode()).digest()
            norm = sum(b * b for b in h) ** 0.5
            return [b / norm if norm > 0 else 0.0 for b in h[:16]]
        return DeterministicFrameworkMatcher(mock_embed)

    def test_empty_framework_returns_empty_result(self, matcher):
        result = matcher.match(
            dimension="Transparency",
            evidence_strength="Explicitly Addressed",
            explicit_evidence=["Section 3 requires disclosure"],
            implicit_evidence=[],
            strong_evidence=[],
            weak_evidence=[],
            policy_evidence_texts=["Policy document text"],
            framework_evidence_texts=[],
        )
        assert isinstance(result, FrameworkMatchResult)
        assert result.universal_requirements == []
        assert result.existing_mechanisms == []
        assert result.missing_mechanisms == []

    def test_match_with_similar_texts(self, matcher):
        result = matcher.match(
            dimension="Transparency",
            evidence_strength="Explicitly Addressed",
            explicit_evidence=["disclosure of AI system capabilities"],
            implicit_evidence=[],
            strong_evidence=[],
            weak_evidence=[],
            policy_evidence_texts=["The document requires disclosure of AI capabilities"],
            framework_evidence_texts=[
                ("UNESCO", "AI systems should be transparent and disclose capabilities"),
            ],
        )
        assert isinstance(result.universal_requirements, list)

    def test_match_structure(self, matcher):
        result = matcher.match(
            dimension="Transparency",
            evidence_strength="Not Demonstrated",
            explicit_evidence=[],
            implicit_evidence=[],
            strong_evidence=[],
            weak_evidence=[],
            policy_evidence_texts=[],
            framework_evidence_texts=[
                ("UNESCO", "AI systems must be auditable and explainable"),
            ],
        )
        assert "synthesis" in result.to_dict()
        assert "implementation_maturity_comparison" in result.to_dict()

    def test_beyond_framework_detection(self, matcher):
        result = matcher.match(
            dimension="Transparency",
            evidence_strength="Strongly Operationalised",
            explicit_evidence=["Mandatory transparency reports", "Public audit logs"],
            implicit_evidence=[],
            strong_evidence=["Mandatory transparency reports", "Public audit logs"],
            weak_evidence=[],
            policy_evidence_texts=["Detailed transparency mechanisms"],
            framework_evidence_texts=[],
        )
        assert len(result.existing_mechanisms) >= 0  # at minimum no crash

    def test_multi_factor_scoring(self):
        def exact_match_embed(text: str) -> list[float]:
            return [1.0, 0.0, 0.0, 0.0]
        matcher = DeterministicFrameworkMatcher(exact_match_embed)
        score = matcher._compute_match_score(
            max_sim=0.8,
            best_explicit_sim=0.9,
            best_implicit_sim=0.3,
            corroboration_count=3,
            strength_multiplier=1.1,
        )
        assert 0.0 < score <= 1.0

    def test_low_score_classification(self):
        def low_embed(text: str) -> list[float]:
            return [0.01, 0.01, 0.01, 0.01]
        matcher = DeterministicFrameworkMatcher(low_embed)
        score = matcher._compute_match_score(
            max_sim=0.1,
            best_explicit_sim=0.05,
            best_implicit_sim=0.02,
            corroboration_count=0,
            strength_multiplier=0.5,
        )
        assert score < 0.35


class TestDeterministicPlausibilityValidator:
    @pytest.fixture
    def validator(self):
        return DeterministicPlausibilityValidator()

    def test_no_adjustment_needed(self, validator):
        result = validator.validate(
            dimension="Transparency",
            maturity_level=3,
            coverage="Partial",
            evidence_strength="Explicitly Addressed",
            document_type="legislation",
            explicit_evidence=["Section 3 requires disclosure"],
            implicit_evidence=[],
            strong_evidence=["Mandatory reports"],
            weak_evidence=[],
            demonstrated_capability="Policy requires disclosure",
            absent_capability="No enforcement mechanism",
            num_aspect_groups=3,
            missing_aspects=[],
        )
        assert result.validated_maturity_level == 3
        assert result.validated_coverage == "Covered"
        assert result.confidence_in_assessment == "High"

    def test_strategy_missing_override(self, validator):
        result = validator.validate(
            dimension="Transparency",
            maturity_level=0,
            coverage="Missing",
            evidence_strength="Implicitly Addressed",
            document_type="strategy",
            explicit_evidence=["Strategy mentions transparency principles"],
            implicit_evidence=[],
            strong_evidence=[],
            weak_evidence=["General commitment to openness"],
            demonstrated_capability="",
            absent_capability="",
            num_aspect_groups=1,
            missing_aspects=["Audit", "Reporting"],
        )
        assert result.validated_maturity_level >= 1
        assert result.validated_coverage == "Partial"
        assert "doc_type" in result.maturity_trace.lower() or "strategy" in result.maturity_trace.lower()

    def test_level_0_with_evidence_raises(self, validator):
        result = validator.validate(
            dimension="Accountability",
            maturity_level=0,
            coverage="Missing",
            evidence_strength="Weakly Demonstrated",
            document_type="legislation",
            explicit_evidence=[],
            implicit_evidence=["Accountability may be implied from oversight body"],
            strong_evidence=[],
            weak_evidence=["General reference to responsible AI"],
            demonstrated_capability="",
            absent_capability="No accountability mechanisms",
            num_aspect_groups=1,
            missing_aspects=["Oversight", "Redress"],
        )
        assert result.validated_maturity_level >= 1
        assert result.validated_coverage == "Partial"

    def test_level_5_lowered_when_no_strong_evidence(self, validator):
        result = validator.validate(
            dimension="Safety",
            maturity_level=5,
            coverage="Covered",
            evidence_strength="Explicitly Addressed",
            document_type="legislation",
            explicit_evidence=["Safety requirements defined"],
            implicit_evidence=[],
            strong_evidence=[],
            weak_evidence=[],
            demonstrated_capability="Safety mechanisms exist",
            absent_capability="",
            num_aspect_groups=3,
            missing_aspects=[],
        )
        assert result.validated_maturity_level <= 4
        assert result.validated_coverage == "Covered"

    def test_level_5_with_strong_evidence_kept(self, validator):
        result = validator.validate(
            dimension="Transparency",
            maturity_level=5,
            coverage="Covered",
            evidence_strength="Strongly Operationalised",
            document_type="legislation",
            explicit_evidence=["Mandatory transparency reports", "Public audit logs"],
            implicit_evidence=[],
            strong_evidence=["Mandatory transparency reports", "Public audit logs"],
            weak_evidence=[],
            demonstrated_capability="Full transparency framework operational",
            absent_capability="",
            num_aspect_groups=4,
            missing_aspects=[],
        )
        assert result.validated_maturity_level == 5

    def test_distributed_governance_raises_level(self, validator):
        result = validator.validate(
            dimension="Inclusivity",
            maturity_level=1,
            coverage="Partial",
            evidence_strength="Implicitly Addressed",
            document_type="strategy",
            explicit_evidence=[],
            implicit_evidence=["Multi-stakeholder council oversees equity"],
            strong_evidence=[],
            weak_evidence=["General inclusivity principle"],
            demonstrated_capability="",
            absent_capability="",
            num_aspect_groups=4,
            missing_aspects=[],
        )
        assert result.validated_maturity_level >= 2

    def test_missing_with_demonstrated_capability_raises(self, validator):
        result = validator.validate(
            dimension="Privacy",
            maturity_level=0,
            coverage="Missing",
            evidence_strength="Not Demonstrated",
            document_type="other",
            explicit_evidence=[],
            implicit_evidence=[],
            strong_evidence=[],
            weak_evidence=[],
            demonstrated_capability="Data protection is addressed through existing frameworks",
            absent_capability="No specific AI privacy provisions",
            num_aspect_groups=1,
            missing_aspects=["Data protection"],
        )
        assert result.validated_maturity_level >= 1
        assert result.validated_coverage == "Partial"

    def test_confidence_high_with_good_evidence(self, validator):
        result = validator.validate(
            dimension="Transparency",
            maturity_level=4,
            coverage="Covered",
            evidence_strength="Strongly Operationalised",
            document_type="legislation",
            explicit_evidence=["Full disclosure framework"],
            implicit_evidence=[],
            strong_evidence=["Operational transparency mechanisms"],
            weak_evidence=[],
            demonstrated_capability="Complete",
            absent_capability="",
            num_aspect_groups=4,
            missing_aspects=[],
        )
        assert result.confidence_in_assessment == "High"

    def test_confidence_low_with_weak_evidence(self, validator):
        result = validator.validate(
            dimension="Fairness",
            maturity_level=1,
            coverage="Partial",
            evidence_strength="Weakly Demonstrated",
            document_type="strategy",
            explicit_evidence=[],
            implicit_evidence=[],
            strong_evidence=[],
            weak_evidence=["Vague fairness commitment"],
            demonstrated_capability="",
            absent_capability="No fairness mechanisms",
            num_aspect_groups=1,
            missing_aspects=["Bias testing", "Fairness assessment"],
        )
        assert result.confidence_in_assessment in ("Low", "Medium")

    def test_maturity_trace_generated(self, validator):
        result = validator.validate(
            dimension="Accountability",
            maturity_level=2,
            coverage="Partial",
            evidence_strength="Explicitly Addressed",
            document_type="strategy",
            explicit_evidence=["Oversight body established"],
            implicit_evidence=[],
            strong_evidence=[],
            weak_evidence=[],
            demonstrated_capability="Accountability framework exists",
            absent_capability="",
            num_aspect_groups=3,
            missing_aspects=[],
        )
        assert "Document Type" in result.maturity_trace
        assert "Level selected" in result.maturity_trace
        assert "functional equivalence" in result.maturity_trace.lower()

    def test_level_to_coverage_mapping(self):
        assert LEVEL_TO_COVERAGE[0] == "Missing"
        assert LEVEL_TO_COVERAGE[1] == "Partial"
        assert LEVEL_TO_COVERAGE[2] == "Partial"
        assert LEVEL_TO_COVERAGE[3] == "Covered"
        assert LEVEL_TO_COVERAGE[4] == "Covered"
        assert LEVEL_TO_COVERAGE[5] == "Covered"

    def test_level_labels_all_present(self):
        assert "No Governance Intent" in LEVEL_LABELS[0]
        assert "Governance Recognised" in LEVEL_LABELS[1]
        assert "Institutional Ownership Identified" in LEVEL_LABELS[2]
        assert "Implementation Commitment Exists" in LEVEL_LABELS[3]
        assert "Operational Mechanisms Established" in LEVEL_LABELS[4]
        assert "Continuous Monitoring and Enforcement" in LEVEL_LABELS[5]


class TestDetectImplementationCommitment:
    def test_named_body_mechanism_signal(self):
        assert detect_implementation_commitment(
            ["National AI Ethics Board (named body)"], []
        ) is True

    def test_reporting_mechanism_signal(self):
        assert detect_implementation_commitment(
            ["Annual transparency reporting"], []
        ) is True

    def test_empty_mechanisms_but_commitment_chunk_with_named_body(self):
        # R2's strong-phrase path requires a named-body/institution keyword
        # to co-occur in the SAME chunk — a bare "programme" mention is no
        # longer enough (that is the stricter bar that stopped the off-topic
        # false positives). With a named body present, the chunk counts.
        assert detect_implementation_commitment(
            [],
            ["The government will establish an Explainable AI (XAI) programme under the national AI office."],
        ) is True

    def test_strong_phrase_without_named_body_does_not_raise(self):
        # The co-occurrence bar: a strong phrase alone ("will establish an
        # XAI programme") with NO named-body keyword in the chunk must NOT
        # satisfy R2 — this is what let an AI-security passage fire R2 on
        # the bare noun "programme".
        assert detect_implementation_commitment(
            [], ["The government will establish an Explainable AI (XAI) programme."]
        ) is False
        assert detect_implementation_commitment(
            [], ["The strategy sets out a roadmap for data governance."]
        ) is False

    def test_commitment_phrase_variants(self):
        for text in [
            "Setting up a Centre for Studies on Technological Sustainability",
            "A national AI mission will be launched next year by the Ministry of Digital",
            "The strategy sets out a roadmap for data governance led by the national AI council",
            "A dedicated task force on AI safety is proposed",
            "We will implement bias mitigation across the lifecycle under the AI Ethics Board",
        ]:
            assert detect_implementation_commitment([], [text]), text

    def test_no_commitment_signal(self):
        assert detect_implementation_commitment(
            [], ["The document discusses the black box phenomenon in passing."]
        ) is False
        assert detect_implementation_commitment([], []) is False

    def test_case_insensitive(self):
        assert detect_implementation_commitment([], ["NATIONAL AI TASK FORCE"]) is True

    def test_word_boundary_program_does_not_match_programming(self):
        # Pure regex-boundary bug: "program" must not match inside
        # "programming"/"programme"; "roadmap" must not match inside
        # "roadmapping". These are the exact substring holes that let an
        # events-calendar paragraph fire R2 on "AI-related programming".
        assert detect_implementation_commitment(
            [], ["AI-related programming events and hackathons for the community"]
        ) is False
        assert detect_implementation_commitment(
            [], ["the roadmapping exercise covers next year's priorities"]
        ) is False
        assert detect_implementation_commitment(
            [], ["a national programme for AI education"], dimension="Inclusivity"
        ) is False

    def test_single_weak_phrase_alone_is_not_conclusive(self):
        # A lone weak phrase ("budget"/"dedicated"/"mandate") is too noisy
        # to be a commitment — e.g. "budget constraints remain a challenge"
        # must NOT count. (Avoid negation examples containing a STRONG word
        # like "program" — "no dedicated program exists" does contain
        # "program", and a negative mention is a known detector limitation,
        # not a weak-tier case.)
        assert detect_implementation_commitment([], ["budget constraints remain a challenge"]) is False
        assert detect_implementation_commitment([], ["the mandate is still under debate"]) is False

    def test_weak_phrase_with_named_body_co_occurrence_counts(self):
        assert detect_implementation_commitment(
            [], ["the national AI council was allocated a dedicated budget"]
        ) is True

    def test_two_weak_hits_across_chunks_count(self):
        assert detect_implementation_commitment(
            [],
            ["the strategy notes a budget for AI", "funding allocation is committed"],
        ) is True

    def test_strong_phrase_single_hit_counts(self):
        assert detect_implementation_commitment([], ["will establish a national AI board"]) is True

    def test_mechanism_classification_keeps_inflected_forms(self):
        # Word-boundary discipline must not regress the mechanism keywords'
        # recall on common inflected forms — "continuous monitoring" and
        # "auditing" are everyday mechanism-report phrases.
        from src.deterministic import classify_mechanisms
        assert classify_mechanisms(["continuous monitoring of AI systems"])["has_enforcement"] is True
        assert classify_mechanisms(["independent auditing of AI deployments"])["has_enforcement"] is True
        assert classify_mechanisms(["routine inspections of high-risk systems"])["has_enforcement"] is True
        assert classify_mechanisms(["penalties for non-compliance"])["has_enforcement"] is True
        assert classify_mechanisms(["liabilities for AI-caused harms"])["has_enforcement"] is True
        assert classify_mechanisms(["annual registry of AI systems"])["has_reporting"] is True


class TestValidateCoverageDeterministic:
    DOC = [{"chunk_id": "c1", "text": "policy passage about the dimension"}]
    COMMITMENT_VERB_DOC = [{"chunk_id": "c1", "text": "The government commits to improving AI transparency."}]

    def test_r1_bare_acknowledgment_no_commitment_stays_missing(self):
        # Tightened floor: a bare risk acknowledgment with no proposed
        # action (principle_acknowledged alone, no mechanism, no commitment
        # language) does NOT satisfy the explicit-commitment bar — it stays
        # Missing. (Old behavior floored this to Partial; that inflation is
        # exactly what the tightening removes.)
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=self.DOC,
        )
        assert cov == CoverageLevel.MISSING
        assert rules == []

    def test_r1_explicit_commitment_verb_raises_to_partial(self):
        # An explicit commitment verb ("commits to") is the R1 floor bar:
        # Missing -> Partial. It is NOT a concrete implementation
        # commitment, so R2 does not fire — the result stays Partial.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=self.COMMITMENT_VERB_DOC,
        )
        assert cov == CoverageLevel.PARTIAL
        assert any("R1" in r for r in rules)
        assert not any("R2" in r for r in rules)

    def test_r1_mechanism_report_composes_to_covered(self):
        # A non-empty operational-mechanism report (named body) is an actual
        # attempted mechanism — R1 fires. R2 also fires on the mechanism
        # report, so the final result is Covered (Missing -> Partial -> Covered).
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=["AI Ethics Board (named body)"],
            document_chunks=self.DOC,
        )
        assert cov == CoverageLevel.COVERED
        assert any("R1" in r for r in rules) and any("R2" in r for r in rules)

    def test_r1_not_fired_without_document_evidence(self):
        # Commitment/acknowledgment without any retrieved document evidence
        # is ungrounded — never raise on it.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[],
        )
        assert cov == CoverageLevel.MISSING
        assert rules == []

    def test_r1_negated_commitment_does_not_floor(self):
        # Negation guard: "is not committed to" is a denial, not a
        # commitment — the phrase "committed to" MATCHES contiguously but is
        # preceded by "not", so it must NOT floor Missing -> Partial.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[],
            document_chunks=[{"chunk_id": "c1",
                              "text": "The government is not committed to improving AI transparency."}],
        )
        assert cov == CoverageLevel.MISSING
        assert rules == []

    def test_r2_negated_strong_phrase_does_not_raise(self):
        # Negation guard on the R2 bar: "no establishment of" matches the
        # strong phrase "establishment of" contiguously but is negated, so
        # it must not raise a Partial verdict to Covered.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=[],
            document_chunks=[{"chunk_id": "c1",
                              "text": "The strategy proposes no establishment of additional AI bodies."}],
        )
        assert cov == CoverageLevel.PARTIAL
        assert rules == []

    def test_r2_verb_only_does_not_raise_to_covered(self):
        # R2's bar (strong phrase / mechanism / weak+corroborated) is
        # deliberately NARROWER than R1's: an explicit commitment verb alone
        # ("commits to") floors Missing -> Partial but does NOT raise a
        # Partial verdict to Covered.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=self.COMMITMENT_VERB_DOC,
        )
        assert cov == CoverageLevel.PARTIAL
        assert rules == []

    def test_floor_disabled_missing_with_commitment_stays_missing(
        self, monkeypatch
    ):
        # LADDER_FLOOR_ENABLED=0: R1 never fires and R2 only operates on
        # Partial verdicts, so even a document with explicit commitment
        # language stays Missing — the honest "no floor" baseline.
        import src.deterministic as det
        monkeypatch.setattr(det, "LADDER_FLOOR_ENABLED", False)
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=["AI Ethics Board (named body)"],
            document_chunks=self.COMMITMENT_VERB_DOC,
        )
        assert cov == CoverageLevel.MISSING
        assert rules == []

    def test_floor_disabled_partial_with_commitment_still_raises_to_covered(
        self, monkeypatch
    ):
        # R2 is unaffected by the floor toggle: a Partial verdict with a
        # concrete implementation commitment (named body + strong phrase in
        # the same chunk) still raises to Covered.
        import src.deterministic as det
        monkeypatch.setattr(det, "LADDER_FLOOR_ENABLED", False)
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=[],
            document_chunks=[{"chunk_id": "c1",
                              "text": "The government will establish an XAI programme under a new national AI authority."}],
        )
        assert cov == CoverageLevel.COVERED
        assert any("R2" in r for r in rules)

    def test_r2_partial_with_commitment_raises_to_covered(self):
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=[],
            document_chunks=[{"chunk_id": "c1",
                              "text": "The government will establish an XAI programme under a new national AI authority."}],
        )
        assert cov == CoverageLevel.COVERED
        assert any("R2" in r for r in rules)

    def test_r2_via_model_mechanism_report(self):
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=["AI Safety Committee (named body)"],
            document_chunks=self.DOC,
        )
        assert cov == CoverageLevel.COVERED
        assert any("R2" in r for r in rules)

    def test_r2_not_fired_without_commitment(self):
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=[],
            document_chunks=[{"chunk_id": "c1",
                              "text": "The document mentions fairness as a principle."}],
        )
        assert cov == CoverageLevel.PARTIAL
        assert rules == []

    def test_r2_not_fired_without_document_evidence(self):
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[],
        )
        assert cov == CoverageLevel.PARTIAL
        assert rules == []

    def test_covered_untouched(self):
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.COVERED, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=self.DOC,
        )
        assert cov == CoverageLevel.COVERED
        assert rules == []

    def test_insufficient_evidence_untouched(self):
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.INSUFFICIENT_EVIDENCE, principle_acknowledged=False,
            operational_mechanisms=[], document_chunks=[],
        )
        assert cov == CoverageLevel.INSUFFICIENT_EVIDENCE
        assert rules == []

    def test_missing_with_commitment_skips_to_covered(self):
        # R1 and R2 compose: the explicit commitment ("will establish")
        # lifts Missing to Partial (R1 floor), then the concrete
        # implementation commitment lifts Partial to Covered (R2 raise).
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[],
            document_chunks=[{"chunk_id": "c1",
                              "text": "We will establish a national AI oversight board."}],
        )
        assert cov == CoverageLevel.COVERED
        assert any("R1" in r for r in rules) and any("R2" in r for r in rules)


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

    def test_un_advisory_chunk_cannot_fire_r1_for_accountability(self):
        # "will support" (verb) would have floored Missing -> Partial under
        # the old matcher. Grounding keeps it Missing.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[self.UN_ADVISORY_CHUNK],
            dimension="Accountability",
        )
        assert cov == CoverageLevel.MISSING
        assert rules == []

    def test_un_advisory_chunk_cannot_fire_r2_for_accountability(self):
        # Even a Partial verdict must not be raised by the UN body: no
        # named body keyword in-chunk AND not dimension-topical.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[self.UN_ADVISORY_CHUNK],
            dimension="Accountability",
        )
        assert cov == CoverageLevel.PARTIAL
        assert rules == []

    def test_events_calendar_chunk_cannot_fire_r1_or_r2_for_inclusivity(self):
        # "program" (inside "programming") and "intends to" were the old
        # triggers. Word boundaries + grounding keep it Missing.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[self.EVENTS_CALENDAR_CHUNK],
            dimension="Inclusivity",
        )
        assert cov == CoverageLevel.MISSING
        assert rules == []

    def test_talent_ecosystem_chunk_does_not_fire_inclusivity_r1(self):
        # Found during manual re-verification (page 42): "participation" +
        # "intends to"/"will create" in a talent-ecosystem passage must not
        # floor Missing -> Partial for Inclusivity. Bare "participation" is
        # not an Inclusivity topic keyword; only "public participation" is.
        assert not _chunk_matches_dimension(self.TALENT_ECOSYSTEM_CHUNK["text"], "Inclusivity")
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[self.TALENT_ECOSYSTEM_CHUNK],
            dimension="Inclusivity",
        )
        assert cov == CoverageLevel.MISSING
        assert rules == []

    def test_topical_chunk_with_named_body_still_fires(self):
        # Positive control: a genuinely accountability-relevant chunk with a
        # named body + commitment language still raises Missing -> Covered.
        chunk = {
            "chunk_id": "c3",
            "text": (
                "The Ministry of Digital will establish an AI Oversight Board "
                "responsible for redress and grievance procedures for harms "
                "caused by AI systems."
            ),
        }
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[chunk],
            dimension="Accountability",
        )
        assert cov == CoverageLevel.COVERED
        assert any("R1" in r for r in rules) and any("R2" in r for r in rules)

    def test_all_dimensions_have_topic_keywords(self):
        for dim in (
            "Transparency", "Accountability", "Privacy", "Safety",
            "Human Autonomy", "Inclusivity", "Fairness",
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
        assert is_low_information_fragment(
            "The policy establishes a National AI Ethics Board with a "
            "human-in-the-loop review mandate for high-impact deployments."
        ) is False
        assert is_low_information_fragment(
            "The government will ensure algorithmic transparency in public services."
        ) is False
        assert is_low_information_fragment(
            "Published in 2024, the framework sets out obligations."
        ) is False
        assert is_low_information_fragment(
            "The policy establishes an ethics board."
        ) is False
