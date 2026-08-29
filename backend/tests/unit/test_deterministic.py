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
    def test_bare_named_body_alone_does_not_raise(self):
        # Tightened path (a): a named body with no reporting/enforcement
        # mechanism alongside it is not a concrete implementation
        # commitment (the same co-occurrence standard the chunk path
        # applies — a body alone never fires R2).
        assert detect_implementation_commitment(
            ["National AI Ethics Board (named body)"], []
        ) is False

    def test_lone_reporting_keyword_alone_does_not_raise(self):
        # The exact India Transparency false positive: a lone reporting
        # keyword ("disclosure"/"reporting") with NO named body must not
        # fire R2's mechanism-report path.
        assert detect_implementation_commitment(
            ["Annual transparency reporting"], []
        ) is False
        assert detect_implementation_commitment(
            ["Labeling and disclosure mechanism for AI-generated virtual content"], []
        ) is False

    def test_named_body_co_occurring_with_reporting_raises(self):
        # The tightened minimum: a named body AND a reporting mechanism
        # together are a concrete implementation commitment.
        assert detect_implementation_commitment(
            ["The AI Safety Committee publishes an annual transparency report"], []
        ) is True

    def test_named_body_co_occurring_with_enforcement_raises(self):
        # Enforcement alongside a named body exceeds the minimum bar.
        assert detect_implementation_commitment(
            ["The AI Ethics Board imposes penalties for non-compliance"], []
        ) is True

    def test_enforcement_keyword_alone_does_not_raise(self):
        # Same discipline as the lone reporting keyword: a single
        # enforcement keyword with no named body is not co-occurrence.
        assert detect_implementation_commitment(
            ["Penalties for non-compliance"], []
        ) is False

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

    def test_named_body_stem_recognizes_minister(self):
        # The Korea Act assigns duties to "the Minister of Science and ICT" —
        # a named body the literal "ministry" keyword cannot match under
        # word-boundary matching. The stem form "minister*" must credit it.
        from src.deterministic import classify_mechanisms, _has_keyword, NAMED_BODY_KEYWORDS
        out = classify_mechanisms(
            ["Minister of Science and ICT confirmation procedure for high-impact AI"]
        )
        assert out["has_named_body"] is True
        assert out["has_operational_mechanism"] is True
        # Inflected forms of the stem match too.
        assert _has_keyword("the ministers agreed on the plan", NAMED_BODY_KEYWORDS)
        assert _has_keyword("a ministerial committee", NAMED_BODY_KEYWORDS)
        # The literal "ministry" entry still works as before.
        assert _has_keyword("the ministry shall report", NAMED_BODY_KEYWORDS)

    def test_reporting_stem_recognizes_noun_forms(self):
        # The Korea Act's duties are phrased as noun forms ("advance
        # notification duty", "labeling and indication requirement") that the
        # verb keyword "notify" cannot match — the noun stems must credit them.
        from src.deterministic import classify_mechanisms
        out = classify_mechanisms(
            ["Advance user notification duty for high-impact AI and GenAI products"]
        )
        assert out["has_reporting"] is True
        assert out["has_operational_mechanism"] is True
        out = classify_mechanisms(
            ["Labeling and indication requirement for AI-generated virtual content"]
        )
        assert out["has_reporting"] is True

    def test_stem_keywords_do_not_match_unrelated_words(self):
        # False-positive spot checks: the stem entries must keep the same
        # boundary discipline as the earlier program/programming fix.
        from src.deterministic import _has_keyword, NAMED_BODY_KEYWORDS, REPORTING_KEYWORDS
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


class TestFunctionalEquivalenceGate:
    """Regression: the evaluator must not mark a dimension Missing when the
    policy contains a governance mechanism expressed in its OWN terminology.
    The ladder's dimension gate is pluggable (dimension_match_fn) so the
    pipeline can admit chunks by semantic equivalence; R1 additionally
    treats OBLIGATION language ("shall notify", "must ensure") as an actual
    mechanism — the deterministic principle → mechanism → operationalized
    distinction. The Korean AI Basic Act is one fixture: its transparency
    duties (advance notification + synthetic-media labelling) are an
    explicit mechanism carrying no literal "transparency/disclosure"
    vocabulary."""

    KOREA_TRANSPARENCY_CHUNK = {
        "chunk_id": "c-kr",
        "text": (
            "AI business operators shall notify users in advance when "
            "deploying high-impact AI or Generative AI and shall label "
            "synthetic media such as virtual sounds, images, and videos "
            "created by AI."
        ),
    }

    def test_keyword_gate_alone_misses_equivalent_terminology(self):
        # Documented miss: the keyword checklist rejects the chunk (no
        # "transparency/disclosure/explainability" vocabulary) — this is the
        # exact false-negative the semantic gate fixes.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[self.KOREA_TRANSPARENCY_CHUNK],
            dimension="Transparency",
        )
        assert cov == CoverageLevel.MISSING
        assert rules == []

    def test_semantic_equivalence_floors_missing_to_partial(self):
        # With a semantic-equivalence gate (the chunk means transparency by
        # substance), the obligation language ("shall notify"/"shall label")
        # is a mechanism → R1 floors Missing -> Partial. NOT Covered: no
        # named body, so R2's co-occurrence bar stays unsatisfied — matching
        # the model's own reasoning on the Korean Act.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[self.KOREA_TRANSPARENCY_CHUNK],
            dimension="Transparency",
            dimension_match_fn=lambda t, d: True,
        )
        assert cov == CoverageLevel.PARTIAL
        assert any("R1" in r for r in rules)
        assert not any("R2" in r for r in rules)

    def test_semantic_gate_still_blocks_off_topic_chunks(self):
        # A semantic predicate that rejects a chunk keeps the UN advisory-
        # body paragraph (which contains "will support") from flooring
        # Accountability — the false-positive protection survives the
        # pluggable gate.
        chunk = {
            "chunk_id": "c-un",
            "text": (
                "We participate actively in international discourse on AI "
                "governance and the UN High-Level Advisory Body on AI will "
                "support the international community's efforts to govern AI."
            ),
        }
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[chunk],
            dimension="Accountability",
            dimension_match_fn=lambda t, d: False,
        )
        assert cov == CoverageLevel.MISSING
        assert rules == []

    def test_principle_mention_without_mechanism_stays_missing(self):
        # principle mentioned → still Missing (maturity reflects the
        # acknowledgment); mechanism exists → Partial. A bare "recognizes
        # the importance of privacy" carries no obligation and must not
        # floor.
        chunk = {
            "chunk_id": "c-p",
            "text": (
                "The policy recognizes the importance of protecting "
                "citizens' privacy in the digital economy."
            ),
        }
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[chunk],
            dimension="Privacy",
            dimension_match_fn=lambda t, d: True,
        )
        assert cov == CoverageLevel.MISSING
        assert rules == []

    def test_functionally_equivalent_privacy_mechanism_floors(self):
        # A confidentiality duty (the policy's own terminology, no "consent"
        # / "data protection" vocabulary) is a privacy mechanism.
        chunk = {
            "chunk_id": "c-conf",
            "text": (
                "Financial institutions shall maintain strict confidentiality "
                "of customers' personal information and are required to "
                "obtain authorization before any disclosure to third parties."
            ),
        }
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[chunk],
            dimension="Privacy",
            dimension_match_fn=lambda t, d: True,
        )
        assert cov == CoverageLevel.PARTIAL
        assert any("R1" in r for r in rules)

    def test_obligation_language_is_a_mechanism_signal(self):
        assert detect_explicit_commitment(
            [],
            ["AI operators shall notify users in advance of high-impact AI deployment."],
            dimension="Transparency",
            dimension_match_fn=lambda t, d: True,
        ) is True
        # Bare acknowledgment: no obligation → not a mechanism.
        assert detect_explicit_commitment(
            [],
            ["The policy recognizes the importance of transparency."],
            dimension="Transparency",
            dimension_match_fn=lambda t, d: True,
        ) is False

    def test_text_contains_mechanism(self):
        from src.deterministic import text_contains_mechanism
        assert text_contains_mechanism(
            "The Ministry shall publish an annual transparency report"
        ) is True
        assert text_contains_mechanism(
            "AI operators must ensure safe deployment of high-risk systems"
        ) is True
        assert text_contains_mechanism(
            "The policy recognizes the importance of fairness"
        ) is False


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

    def test_r1_named_body_mechanism_report_floors_to_partial_only(self):
        # A named-body mechanism report is an actual attempted mechanism —
        # R1 (the floor) fires. But under the tightened R2 bar a bare named
        # body with no reporting/enforcement mechanism alongside is NOT an
        # implementation commitment, so the final verdict is Partial, not
        # Covered (Missing -> Partial; R2 does not fire).
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=["AI Ethics Board (named body)"],
            document_chunks=self.DOC,
        )
        assert cov == CoverageLevel.PARTIAL
        assert any("R1" in r for r in rules)
        assert not any("R2" in r for r in rules)

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
        # R2's mechanism-report path requires named-body + reporting /
        # enforcement co-occurrence (tightened): a body that also reports
        # is a concrete implementation commitment.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=["AI Safety Committee publishes annual transparency reports"],
            document_chunks=self.DOC,
        )
        assert cov == CoverageLevel.COVERED
        assert any("R2" in r for r in rules)

    def test_lone_disclosure_keyword_does_not_raise_partial_to_covered(self):
        """Regression — India Transparency. R2's path (a) previously raised a
        Partial verdict to Covered because the mechanism report contained the
        reporting keyword 'disclosure' (labeling/notification mechanisms)
        with NO named body. The tightened bar (named body co-occurring with
        a reporting/enforcement mechanism) must keep the verdict Partial,
        consistent with the model's own reasoning (explicit gaps listed: no
        explainability, documentation, or logging standards)."""
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=[
                "Advance notification requirement for high-impact AI and Generative AI",
                "Labeling and disclosure mechanism for AI-generated virtual content",
            ],
            document_chunks=self.DOC,
        )
        assert cov == CoverageLevel.PARTIAL
        assert rules == []

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

    def test_procedural_authority_does_not_floor_missing(self):
        # Relevance gate passes (topically adjacent to Env Sustainability —
        # data centres / learning data consume resources), but the
        # substantive gate rejects the chunk: no environmental governance
        # requirement. R1 must NOT floor Missing -> Partial.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[self.KOREA_ENV_PROCEDURAL],
            dimension="Environmental Sustainability",
            dimension_match_fn=lambda t, d: True,
            substantive_match_fn=lambda t, d: False,
        )
        assert cov == CoverageLevel.MISSING
        assert rules == []

    def test_procedural_authority_does_not_raise_partial_to_covered(self):
        # Same passage on a Partial verdict: R2 must not raise to Covered.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[self.KOREA_ENV_PROCEDURAL],
            dimension="Environmental Sustainability",
            dimension_match_fn=lambda t, d: True,
            substantive_match_fn=lambda t, d: False,
        )
        assert cov == CoverageLevel.PARTIAL
        assert rules == []

    def test_procedural_privacy_passage_does_not_fire_ladder(self):
        # The Korea Privacy pool passage (public-institution decision-making)
        # must stay inert for Privacy despite obligation language.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[self.KOREA_PRIV_PROCEDURAL],
            dimension="Privacy",
            dimension_match_fn=lambda t, d: True,
            substantive_match_fn=lambda t, d: False,
        )
        assert cov == CoverageLevel.MISSING
        assert rules == []

    def test_substantive_mechanism_floors_missing_to_partial(self):
        # Positive control (1): a genuinely substantive environmental
        # mechanism (energy/carbon reporting duty) passes the substantive
        # gate -> R1 floors Missing -> Partial. No named body + reporting in
        # the same mechanism sentence here, so R2 does not fire.
        chunk = {
            "chunk_id": "c-env",
            "text": (
                "AI data centres shall report their annual energy consumption "
                "and carbon emissions and implement energy efficiency measures."
            ),
        }
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[chunk],
            dimension="Environmental Sustainability",
            dimension_match_fn=lambda t, d: True,
            substantive_match_fn=lambda t, d: True,
        )
        assert cov == CoverageLevel.PARTIAL
        assert any("R1" in r for r in rules)
        assert not any("R2" in r for r in rules)

    def test_substantive_mechanism_with_named_body_raises_to_covered(self):
        # Positive control (2): a concrete, dimension-specific governance
        # requirement with a named body + reporting duty is eligible for
        # Covered — the substantive gate passes AND R2's implementation-
        # commitment bar is met.
        chunk = {
            "chunk_id": "c-env2",
            "text": (
                "The Ministry of Environment shall establish a mandatory "
                "annual energy and carbon reporting programme for AI data "
                "centres, with penalties for non-compliance."
            ),
        }
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[chunk],
            dimension="Environmental Sustainability",
            dimension_match_fn=lambda t, d: True,
            substantive_match_fn=lambda t, d: True,
        )
        assert cov == CoverageLevel.COVERED
        assert any("R2" in r for r in rules)

    def test_terminology_different_mechanism_still_recognized(self):
        # Regression (4): a mechanism expressed in the policy's OWN
        # terminology (no "transparency/disclosure/consent" vocabulary) is
        # still recognized when the substantive gate admits it by MEANING —
        # the semantic-equivalence fix survives the new precision gate.
        chunk = {
            "chunk_id": "c-conf",
            "text": (
                "AI business operators shall notify users in advance when "
                "deploying high-impact AI and shall label synthetic media "
                "created by AI."
            ),
        }
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[chunk],
            dimension="Transparency",
            dimension_match_fn=lambda t, d: True,
            substantive_match_fn=lambda t, d: True,
        )
        assert cov == CoverageLevel.PARTIAL
        assert any("R1" in r for r in rules)

    def test_substantive_gate_defaults_to_dimension_gate(self):
        # Backward compatibility: when no substantive gate is supplied, the
        # dimension gate alone governs (no stricter bar) — existing
        # behavior is preserved.
        chunk = {
            "chunk_id": "c-env",
            "text": (
                "AI data centres shall report their annual energy consumption "
                "and carbon emissions."
            ),
        }
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[chunk],
            dimension="Environmental Sustainability",
            dimension_match_fn=lambda t, d: True,
        )
        assert cov == CoverageLevel.PARTIAL
        assert any("R1" in r for r in rules)

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

    def test_mixed_chunk_unrelated_strong_mechanism_does_not_promote(self):
        # The energy-reporting sentence is substantive for Env; the
        # institute sentence carries a strong phrase ("shall establish") +
        # named body ("Minister") but is NOT an environmental mechanism. The
        # whole chunk passes the chunk-level gate (it contains "energy"), so
        # the old code raised Partial -> Covered on the co-located
        # institute sentence. The sentence-level gate keeps it Partial.
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[self.MIXED_ENV_CHUNK],
            dimension="Environmental Sustainability",
            dimension_match_fn=lambda t, d: True,
            substantive_match_fn=(
                lambda t, d: "energy" in t.lower() or "carbon" in t.lower()
            ),
        )
        assert cov == CoverageLevel.PARTIAL
        assert rules == []

    def test_mixed_chunk_substantive_sentence_with_strong_mechanism_promotes(self):
        # Positive control for the same mechanism: when the sentence carrying
        # the strong phrase + named body IS substantively about the
        # dimension, R2 may promote. (The institute sentence is dropped and
        # the reporting duty is given the named body + strong language in
        # the SAME sentence.)
        chunk = {
            "chunk_id": "c-mixed2",
            "text": (
                "The Ministry of Environment shall establish a mandatory "
                "annual energy and carbon reporting programme for AI data "
                "centres, with penalties for non-compliance. "
                "Unrelated boilerplate about administrative procedure."
            ),
        }
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[chunk],
            dimension="Environmental Sustainability",
            dimension_match_fn=lambda t, d: True,
            substantive_match_fn=(
                lambda t, d: "energy" in t.lower() or "carbon" in t.lower()
            ),
        )
        assert cov == CoverageLevel.COVERED
        assert any("R2" in r for r in rules)

    def test_substantive_mechanism_without_implementation_stays_partial(self):
        # A substantive dimension-specific mechanism WITHOUT the strong
        # phrase + named body co-occurrence bar is Partial, never Covered:
        # the obligation duty alone ("shall report") cannot raise.
        chunk = {
            "chunk_id": "c-env3",
            "text": (
                "AI data centres shall report their annual energy consumption "
                "and carbon emissions and implement energy efficiency "
                "measures."
            ),
        }
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.PARTIAL, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[chunk],
            dimension="Environmental Sustainability",
            dimension_match_fn=lambda t, d: True,
            substantive_match_fn=lambda t, d: True,
        )
        assert cov == CoverageLevel.PARTIAL
        assert rules == []

    def test_mixed_chunk_procedural_obligation_sentence_does_not_floor(self):
        # The same co-location discipline applies to the R1 floor: a chunk
        # whose substantive sentence carries NO obligation language, but
        # whose PROCEDURAL sentence does ("the Minister shall promote…"),
        # must not floor Missing -> Partial on the boilerplate. Only the
        # sentence bearing the obligation may fire R1.
        chunk = {
            "chunk_id": "c-mixed3",
            "text": (
                "The policy recognizes the environmental impact of AI data "
                "centres and their lifecycle footprint. "
                "The Minister of Science and ICT shall promote measures to "
                "facilitate the production, collection, management, "
                "distribution, utilization of Learning Data."
            ),
        }
        cov, rules = validate_coverage_deterministic(
            CoverageLevel.MISSING, principle_acknowledged=True,
            operational_mechanisms=[], document_chunks=[chunk],
            dimension="Environmental Sustainability",
            dimension_match_fn=lambda t, d: True,
            substantive_match_fn=(
                lambda t, d: "environment" in t.lower() or "energy" in t.lower()
            ),
        )
        assert cov == CoverageLevel.MISSING
        assert rules == []

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
