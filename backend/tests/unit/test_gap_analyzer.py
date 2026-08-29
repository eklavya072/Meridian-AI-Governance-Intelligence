import pytest
from src.gap_analyzer import (
    compute_calibrated_confidence, compute_risk, build_framework_synthesis,
    resolve_priority, compute_decision_analytics, estimate_phase_timelines,
    BEST_PRACTICES_OPENING,
    CORE_DIMENSIONS, DIMENSION_CLUSTERS, COVERAGE_RANK,
    GOVERNANCE_DIMENSIONS, GapAnalyzer,
)
from src.models import (
    RetrievedEvidence, GovernanceGap, CoverageLevel, RiskLevel, ModuleCitation,
    Priority, GovernanceMaturity, Module2Recommendation,
)


def make_evidence(similarity: float | None = None) -> list[RetrievedEvidence]:
    return [
        RetrievedEvidence(
            chunk_id=f"c{i}",
            text=f"chunk {i}",
            source_framework="OECD AI Principles",
            similarity_score=similarity,
        )
        for i in range(5)
    ]


class TestComputeCalibratedConfidence:
    def test_empty_evidence_returns_zero(self):
        conf, method = compute_calibrated_confidence([])
        assert conf == 0.0
        assert "No evidence" in method

    def test_evidence_with_scores_returns_positive(self):
        ev = [RetrievedEvidence(
            chunk_id="c0", text="text", source_framework="OECD",
            similarity_score=0.85,
        )]
        conf, method = compute_calibrated_confidence(ev)
        assert conf > 0.0
        assert "GeoMean" in method

    def test_confidence_varies_with_similarity(self):
        low_ev = make_evidence(0.60)
        high_ev = make_evidence(0.90)
        low_conf, _ = compute_calibrated_confidence(low_ev)
        high_conf, _ = compute_calibrated_confidence(high_ev)
        assert low_conf < high_conf

    def test_mixed_none_and_valid_scores(self):
        ev = [
            RetrievedEvidence(chunk_id="c0", text="t", source_framework="OECD", similarity_score=0.9),
            RetrievedEvidence(chunk_id="c1", text="t", source_framework="OECD", similarity_score=None),
            RetrievedEvidence(chunk_id="c2", text="t", source_framework="OECD", similarity_score=0.7),
        ]
        conf, _ = compute_calibrated_confidence(ev)
        assert conf > 0.0

    def test_single_source(self):
        ev = [RetrievedEvidence(chunk_id="c0", text="t", source_framework="fw1",
                                similarity_score=0.5)]
        conf, _ = compute_calibrated_confidence(ev)
        assert 0 < conf < 1.0

    def test_clamped_range(self):
        ev = make_evidence(0.99)
        conf, _ = compute_calibrated_confidence(ev, coverage_level=CoverageLevel.COVERED)
        assert conf <= 1.0
        assert conf > 0.0


def make_gap(dimension: str, coverage: str) -> GovernanceGap:
    return GovernanceGap(
        dimension=dimension,
        coverage=CoverageLevel(coverage),
        gap_found=coverage != "Covered",
        reason_flagged="test",
        recommendation="test",
        evidence=[],
    )


class TestComputeRisk:
    def test_covered_is_low(self):
        risk, reason = compute_risk(CoverageLevel.COVERED, "Transparency")
        assert risk == RiskLevel.LOW

    def test_core_partial_is_medium(self):
        risk, reason = compute_risk(CoverageLevel.PARTIAL, "Transparency")
        assert risk == RiskLevel.MEDIUM
        assert "Core dimension" in reason

    def test_core_missing_is_high(self):
        risk, reason = compute_risk(CoverageLevel.MISSING, "Accountability")
        assert risk == RiskLevel.HIGH
        assert "Core dimension" in reason

    def test_insufficient_evidence_returns_insufficient(self):
        risk, reason = compute_risk(CoverageLevel.INSUFFICIENT_EVIDENCE, "Transparency")
        assert risk == RiskLevel.INSUFFICIENT_EVIDENCE
        assert "Insufficient evidence" in reason

    def test_compounding_with_worse_coverage_increases(self):
        other = [make_gap("Accountability", "Missing")]
        risk, reason = compute_risk(CoverageLevel.PARTIAL, "Transparency", other_gaps=other)
        assert risk == RiskLevel.HIGH
        assert "same cluster" in reason

    def test_compounding_isolated_does_not_increase(self):
        other = [make_gap("Privacy", "Missing")]
        risk, reason = compute_risk(CoverageLevel.PARTIAL, "Transparency", other_gaps=other)
        assert risk == RiskLevel.MEDIUM
        assert "same cluster" not in reason

    def test_coverage_distinction(self):
        partial_risks = set()
        missing_risks = set()
        for dim in GOVERNANCE_DIMENSIONS:
            partial_risks.add(
                compute_risk(CoverageLevel.PARTIAL, dim)[0].value
            )
            missing_risks.add(
                compute_risk(CoverageLevel.MISSING, dim)[0].value
            )
        assert partial_risks != missing_risks


class FakeVectorStore:
    """Minimal stub: records chunk lookups, never finds chunks."""
    def __init__(self):
        self.lookups = []

    def get_chunk(self, chunk_id: str):
        self.lookups.append(chunk_id)
        return None


class TestNoCitationSentinel:
    def _analyzer(self, store: FakeVectorStore) -> GapAnalyzer:
        a = GapAnalyzer.__new__(GapAnalyzer)
        a.vector_store = store
        a.nli_verifier = None
        return a

    @pytest.mark.parametrize("chunk_id", [
        "insufficient evidence for citation",
        "insufficient evidence",
        "Insufficient Evidence For Citation",
        "no citation available",
        "no supporting passage",
    ])
    def test_sentinel_chunk_id_never_looked_up(self, chunk_id):
        """The sentinel is an explicit 'no citation' state — it must NOT be
        run through the vector-store lookup path (which would report a
        confusing 'Chunk does not exist' failure)."""
        store = FakeVectorStore()
        analyzer = self._analyzer(store)
        citations = analyzer._verify_module_citations(
            [{"chunk_id": chunk_id, "quote": "some claim"}],
            default_source="Test Framework",
            source_type="framework",
        )
        assert len(citations) == 1
        c = citations[0]
        assert isinstance(c, ModuleCitation)
        assert c.no_citation is True
        assert c.chunk_id == ""
        assert store.lookups == []

    def test_sentinel_quote_also_detected(self):
        store = FakeVectorStore()
        analyzer = self._analyzer(store)
        citations = analyzer._verify_module_citations(
            [{"chunk_id": "", "quote": "insufficient evidence for citation"}],
            default_source="Test",
            source_type="framework",
        )
        assert len(citations) == 1
        assert citations[0].no_citation is True
        assert store.lookups == []

    def test_real_chunk_id_still_looked_up(self):
        store = FakeVectorStore()
        analyzer = self._analyzer(store)
        citations = analyzer._verify_module_citations(
            [{"chunk_id": "9f3a2b1c", "quote": "real quote"}],
            default_source="Test",
            source_type="framework",
        )
        assert len(citations) == 1
        assert citations[0].no_citation is False
        assert store.lookups == ["9f3a2b1c"]
        assert "Chunk does not exist" in (citations[0].verification or {}).get("failure_reason", "")

    def test_verbatim_quote_starting_with_sentinel_prefix_keeps_real_chunk(self):
        """A genuine quote like 'Insufficient evidence exists...' with a real
        chunk_id must NOT be classified as no_citation — only exact sentinel
        membership counts on the quote side."""
        store = FakeVectorStore()
        analyzer = self._analyzer(store)
        citations = analyzer._verify_module_citations(
            [{"chunk_id": "9f3a2b1c", "quote": "Insufficient evidence exists to demonstrate compliance."}],
            default_source="Test",
            source_type="framework",
        )
        assert len(citations) == 1
        assert citations[0].no_citation is False
        assert store.lookups == ["9f3a2b1c"]

    def test_empty_chunk_id_keeps_existing_behavior(self):
        store = FakeVectorStore()
        analyzer = self._analyzer(store)
        citations = analyzer._verify_module_citations(
            [{"chunk_id": "", "quote": "plain quote"}],
            default_source="Test",
            source_type="framework",
        )
        assert len(citations) == 1
        assert citations[0].no_citation is False


class TestAnalysisErrorState:
    """Regression: LLM/provider failures must NEVER be saved as genuine
    'Insufficient Evidence' findings. A failed analysis is not a verdict."""

    def test_build_error_gap_marks_analysis_error(self):
        a = GapAnalyzer.__new__(GapAnalyzer)
        gap = a._build_error_gap("Fairness", "All Gemini API keys exhausted: 429")
        assert gap.analysis_error == "All Gemini API keys exhausted: 429"
        assert "Analysis failed" in gap.reason_flagged
        assert gap.risk_reason == "Analysis Error"
        assert gap.confidence_score == 0.0

    def test_build_insufficient_gap_has_no_analysis_error(self):
        a = GapAnalyzer.__new__(GapAnalyzer)
        gap = a._build_insufficient_gap("Fairness")
        assert gap.analysis_error is None
        assert "Insufficient evidence" in gap.reason_flagged
        assert gap.risk_reason == "Insufficient Evidence"

    def test_summary_counts_failures_separately_from_insufficient(self):
        a = GapAnalyzer.__new__(GapAnalyzer)
        ok = a._build_insufficient_gap("Inclusivity")
        failed = a._build_error_gap("Fairness", "quota exhausted")
        summary = a._generate_summary([ok, failed])
        assert "1 dimension(s) could not be analysed (Fairness)" in summary
        assert "1 dimensions had insufficient evidence" in summary

    def test_failed_gap_never_counts_as_insufficient_finding(self):
        a = GapAnalyzer.__new__(GapAnalyzer)
        failed = a._build_error_gap("Fairness", "quota exhausted")
        summary = a._generate_summary([failed])
        assert "had insufficient evidence" not in summary
        assert "could not be analysed" in summary

    def test_error_gap_model_roundtrip_keeps_field(self):
        a = GapAnalyzer.__new__(GapAnalyzer)
        failed = a._build_error_gap("Fairness", "provider error")
        data = failed.model_dump()
        assert data["analysis_error"] == "provider error"
        rebuilt = GovernanceGap(**data)
        assert rebuilt.analysis_error == "provider error"


class TestDimensionExceptionWiring:
    """The regression the user actually hit: a provider exception (e.g. 429
    quota exhaustion) inside the per-dimension loop must surface as an
    analysis_error gap, NOT as a genuine 'Insufficient Evidence' finding."""

    class _RaisingProvider:
        model_name = "gemini-3.6-flash"
        tier = "primary"

    class _EmptyStore:
        def get_chunk(self, chunk_id):
            return None

    def test_exception_propagates_from_combined_call(self, monkeypatch):
        import src.gap_analyzer as ga

        def _boom(*args, **kwargs):
            raise RuntimeError("All Gemini API keys exhausted: 429 RESOURCE_EXHAUSTED")

        monkeypatch.setattr(ga, "generate_with_retry", _boom)

        # Build an analyzer whose retrieval returns a non-empty result so the
        # code reaches the LLM call, which then raises. The exception must
        # propagate OUT of _analyze_dimension_combined so analyze()'s
        # except-handler can build the analysis_error gap.
        from src.retrieval import ModuleRetrievalResult
        analyzer = ga.GapAnalyzer.__new__(ga.GapAnalyzer)
        analyzer.vector_store = self._EmptyStore()
        analyzer.provider = self._RaisingProvider()
        analyzer.consistency_validator = ga.ConsistencyValidator()

        retrieval = ModuleRetrievalResult(
            dimension="Fairness",
            document_chunks=[{"chunk_id": "d1", "text": "doc text", "module_role": "document"}],
            module1_chunks=[{"chunk_id": "n1", "text": "norm text", "module_role": "module_1_normative"}],
            module2_chunks=[{"chunk_id": "p1", "text": "prac text", "module_role": "module_2_practical"}],
        )
        retrieval.total_chunks = 3

        with pytest.raises(RuntimeError, match="exhausted"):
            analyzer._analyze_dimension_combined("Fairness", retrieval)

    def test_analyze_except_handler_uses_error_gap(self, monkeypatch):
        import src.gap_analyzer as ga
        from src.gap_analyzer import GapAnalysisResult

        def _boom(*args, **kwargs):
            raise RuntimeError("quota exhausted")

        monkeypatch.setattr(ga, "generate_with_retry", _boom)

        class _VS:
            def get_all_frameworks(self):
                return ["UNESCO Recommendation on the Ethics of AI"]
            def get_chunk(self, chunk_id):
                return None

        class _RP:
            def retrieve_module_chunks(self, **kwargs):
                from src.retrieval import ModuleRetrievalResult
                r = ModuleRetrievalResult(
                    dimension=kwargs.get("dimension"),
                    document_chunks=[{"chunk_id": "d1", "text": "t", "module_role": "document"}],
                    module1_chunks=[{"chunk_id": "n1", "text": "t", "module_role": "module_1_normative"}],
                    module2_chunks=[{"chunk_id": "p1", "text": "t", "module_role": "module_2_practical"}],
                )
                r.total_chunks = 3
                return r

        analyzer = ga.GapAnalyzer.__new__(ga.GapAnalyzer)
        analyzer.vector_store = _VS()
        analyzer.provider = self._RaisingProvider()
        analyzer.retrieval_pipeline = _RP()
        analyzer.consistency_validator = ga.ConsistencyValidator()
        analyzer.nli_verifier = None

        result = analyzer.analyze(
            document_text="x",
            document_name="policy.pdf",
            workspace_id="ws",
            country="India",
        )
        assert isinstance(result, GapAnalysisResult)
        failed = [g for g in result.governance_gaps if g.analysis_error]
        assert len(failed) == len(result.governance_gaps)
        for g in failed:
            assert "quota exhausted" in g.analysis_error
            assert g.risk_reason == "Analysis Error"
        # Summary must say the dimensions could not be analysed — never
        # 'had insufficient evidence'.
        assert "could not be analysed" in result.summary
        assert "had insufficient evidence" not in result.summary

    def test_parallel_analyze_preserves_order_and_callback(self, monkeypatch):
        """The bounded-parallel dimension loop must be observably identical
        to the sequential one: results in GOVERNANCE_DIMENSIONS order, one
        callback per dimension, an accurate call count, and no duplicate or
        missing dimensions — regardless of which worker finishes first."""
        import src.gap_analyzer as ga
        from src.gap_analyzer import GapAnalysisResult, GOVERNANCE_DIMENSIONS

        def _fake_generate(**kwargs):
            return _FakeCombined(coverage="Covered")

        monkeypatch.setattr(ga, "generate_with_retry", _fake_generate)

        class _VS:
            def get_all_frameworks(self):
                return ["UNESCO Recommendation on the Ethics of AI"]
            def get_chunk(self, chunk_id):
                return None

        class _RP:
            def retrieve_module_chunks(self, **kwargs):
                from src.retrieval import ModuleRetrievalResult
                r = ModuleRetrievalResult(
                    dimension=kwargs.get("dimension"),
                    document_chunks=[{"chunk_id": "d1", "text": "t", "module_role": "document"}],
                    module1_chunks=[{"chunk_id": "n1", "text": "t", "module_role": "module_1_normative"}],
                    module2_chunks=[{"chunk_id": "p1", "text": "t", "module_role": "module_2_practical"}],
                )
                r.total_chunks = 3
                return r

        analyzer = ga.GapAnalyzer.__new__(ga.GapAnalyzer)
        analyzer.vector_store = _VS()
        analyzer.provider = self._RaisingProvider()
        analyzer.retrieval_pipeline = _RP()
        analyzer.consistency_validator = ga.ConsistencyValidator()
        analyzer.nli_verifier = None

        called: list[str] = []
        result = analyzer.analyze(
            document_text="x",
            document_name="policy.pdf",
            workspace_id="ws",
            country="India",
            dimension_callback=lambda d, gap, info: called.append(d),
        )
        assert isinstance(result, GapAnalysisResult)
        # Ordering guarantee: the report lists dimensions canonically even
        # though the workers finish out of order.
        assert [g.dimension for g in result.governance_gaps] == list(GOVERNANCE_DIMENSIONS)
        assert all(not g.analysis_error for g in result.governance_gaps)
        # One callback per dimension (fire order is nondeterministic).
        assert sorted(called) == sorted(GOVERNANCE_DIMENSIONS)
        assert len(called) == len(GOVERNANCE_DIMENSIONS)
        # Covered dimensions cost exactly one LLM call each.
        assert result.llm_call_count == len(GOVERNANCE_DIMENSIONS)


class TestDecisionAnalytics:
    """Executive decision analytics — deterministic aggregates for dashboards
    and the research paper's evaluation section."""

    def _gap(self, dim, coverage, maturity=GovernanceMaturity.DEVELOPING,
             priority=None, confidence=0.6, failed=False):
        m2 = None
        if priority is not None:
            m2 = Module2Recommendation(dimension=dim, priority=priority)
        if failed:
            return GovernanceGap(
                dimension=dim, coverage=CoverageLevel.INSUFFICIENT_EVIDENCE,
                reason_flagged="Analysis failed", recommendation="",
                analysis_error="quota",
            )
        return GovernanceGap(
            dimension=dim,
            coverage=CoverageLevel(coverage),
            gap_found=coverage != "Covered",
            reason_flagged="x",
            recommendation="y",
            evidence=[],
            governance_maturity=maturity,
            confidence_score=confidence,
            module_2=m2,
        )

    def test_counts_and_failed_are_separate(self):
        gaps = [
            self._gap("Transparency", "Covered", GovernanceMaturity.ESTABLISHED, confidence=0.9),
            self._gap("Privacy", "Partial", GovernanceMaturity.DEVELOPING, confidence=0.5),
            self._gap("Fairness", "Missing", GovernanceMaturity.UNADDRESSED, confidence=0.2),
            self._gap("Safety", "Insufficient Evidence"),
            self._gap("Accountability", "Insufficient Evidence", failed=True),
        ]
        a = compute_decision_analytics(gaps)
        assert a["covered"] == 1
        assert a["partial"] == 1
        assert a["missing"] == 1
        assert a["insufficient_evidence"] == 1
        assert a["analysis_failed"] == 1

    def test_maturity_index_is_mean_of_stage_scores(self):
        """The composite index averages explicit STAGE SCORES, not ordinal
        ranks — a mean of ranks prices every step between stages the same,
        which is what made the old linear-rank average indefensible."""
        gaps = [
            self._gap("Transparency", "Covered", GovernanceMaturity.ESTABLISHED),
            self._gap("Privacy", "Covered", GovernanceMaturity.ESTABLISHED),
            self._gap("Fairness", "Partial", GovernanceMaturity.DEVELOPING),
        ]
        a = compute_decision_analytics(gaps)
        # (100 + 100 + 78) / 3 = 92.7. The previous linear rank average gave
        # 88.9, which priced the Unaddressed→Emerging step identically to the
        # Operationalized→Institutionalized one — see MATURITY_STAGE_SCORE.
        assert a["maturity_index"] == 92.7
        assert a["assessed_dimensions"] == 3
        # Full distribution histogram — a single weakest-dimension LABEL used
        # to be derived from this too, but it was never shown anywhere in the
        # frontend and duplicated what this histogram already carries, so it
        # was dropped from the returned dict rather than kept as dead weight.
        assert a["maturity_distribution"] == {
            "Unaddressed": 0, "Emerging": 0, "Delegated": 0,
            "Operationalized": 1, "Institutionalized": 2,
        }

    def test_one_weak_dimension_still_pulls_down_the_index(self):
        """A single Unaddressed dimension among seven Established ones drags
        the composite index down proportionally to its stage score, even
        though it is only one of eight assessed dimensions."""
        gaps = [
            self._gap("Transparency", "Covered", GovernanceMaturity.ESTABLISHED)
            for _ in range(7)
        ] + [self._gap("Privacy", "Missing", GovernanceMaturity.UNADDRESSED)]
        a = compute_decision_analytics(gaps)
        # (7*100 + 0) / 8 = 87.5
        assert a["maturity_index"] == 87.5

    def test_maturity_index_ranges_0_to_100(self):
        low = [self._gap("T", "Missing", GovernanceMaturity.UNADDRESSED) for _ in range(3)]
        high = [self._gap("T", "Covered", GovernanceMaturity.ESTABLISHED) for _ in range(3)]
        assert compute_decision_analytics(low)["maturity_index"] == 0.0
        assert compute_decision_analytics(high)["maturity_index"] == 100.0

    def test_distribution_counts_each_stage(self):
        gaps = [
            self._gap("T", "Covered", GovernanceMaturity.ESTABLISHED),
            self._gap("P", "Covered", GovernanceMaturity.ESTABLISHED),
            self._gap("S", "Partial", GovernanceMaturity.DEVELOPING),
            self._gap("F", "Missing", GovernanceMaturity.EMERGING),
        ]
        a = compute_decision_analytics(gaps)
        assert a["maturity_distribution"]["Institutionalized"] == 2
        assert a["maturity_distribution"]["Operationalized"] == 1
        assert a["maturity_distribution"]["Emerging"] == 1
        assert sum(a["maturity_distribution"].values()) == 4

    def test_highest_priority_sorted_most_urgent_first(self):
        gaps = [
            self._gap("Privacy", "Missing", GovernanceMaturity.UNADDRESSED, priority=Priority.CRITICAL),
            self._gap("Transparency", "Partial", GovernanceMaturity.EMERGING, priority=Priority.HIGH),
            self._gap("Fairness", "Partial", GovernanceMaturity.DEVELOPING, priority=Priority.MEDIUM),
            self._gap("Inclusivity", "Covered", GovernanceMaturity.ESTABLISHED, priority=None),
        ]
        a = compute_decision_analytics(gaps)
        assert a["highest_priority_dimensions"] == ["Privacy", "Transparency"]

    def test_strongest_dimension_by_maturity_then_confidence(self):
        gaps = [
            self._gap("Transparency", "Covered", GovernanceMaturity.ESTABLISHED, confidence=0.7),
            self._gap("Privacy", "Covered", GovernanceMaturity.ESTABLISHED, confidence=0.95),
            self._gap("Fairness", "Partial", GovernanceMaturity.DEVELOPING, confidence=0.5),
        ]
        a = compute_decision_analytics(gaps)
        # Tie on maturity (Managed) → confidence tie-break picks Privacy.
        assert a["strongest_dimension"] == "Privacy"

    def test_all_failed_returns_not_assessed(self):
        gaps = [
            self._gap("Transparency", "Insufficient Evidence", failed=True),
            self._gap("Privacy", "Insufficient Evidence", failed=True),
        ]
        a = compute_decision_analytics(gaps)
        assert a["maturity_index"] == 0.0
        assert a["assessed_dimensions"] == 0
        assert all(v == 0 for v in a["maturity_distribution"].values())
        assert a["strongest_dimension"] == ""
        assert a["highest_priority_dimensions"] == []
        assert a["average_confidence"] == 0.0

    def test_average_confidence_across_assessed(self):
        gaps = [
            self._gap("Transparency", "Covered", confidence=0.8),
            self._gap("Privacy", "Partial", confidence=0.4),
        ]
        a = compute_decision_analytics(gaps)
        assert a["average_confidence"] == pytest.approx(0.6, abs=0.001)


class TestResolvePriority:
    """Coverage-tiered priority is deterministic code, never LLM judgment."""

    def test_covered_returns_none(self):
        assert resolve_priority(CoverageLevel.COVERED, "Transparency") is None

    def test_insufficient_evidence_returns_none(self):
        assert (
            resolve_priority(CoverageLevel.INSUFFICIENT_EVIDENCE, "Transparency")
            is None
        )

    def test_partial_defaults_medium(self):
        assert resolve_priority(CoverageLevel.PARTIAL, "Transparency") == Priority.MEDIUM

    def test_missing_defaults_high(self):
        assert resolve_priority(CoverageLevel.MISSING, "Transparency") == Priority.HIGH

    def test_partial_compounding_escalates_to_high(self):
        other = [make_gap("Accountability", "Missing")]
        assert (
            resolve_priority(CoverageLevel.PARTIAL, "Transparency", other_gaps=other)
            == Priority.HIGH
        )

    def test_missing_compounding_escalates_to_critical(self):
        other = [make_gap("Accountability", "Missing")]
        assert (
            resolve_priority(CoverageLevel.MISSING, "Transparency", other_gaps=other)
            == Priority.CRITICAL
        )

    def test_compounding_isolated_does_not_escalate(self):
        # Privacy is in a different cluster than Transparency
        other = [make_gap("Privacy", "Missing")]
        assert (
            resolve_priority(CoverageLevel.PARTIAL, "Transparency", other_gaps=other)
            == Priority.MEDIUM
        )

    def test_covered_never_escalates(self):
        other = [make_gap("Accountability", "Missing")]
        assert resolve_priority(CoverageLevel.COVERED, "Transparency", other_gaps=other) is None

    def test_all_dimensions_have_consistent_defaults(self):
        for dim in GOVERNANCE_DIMENSIONS:
            assert resolve_priority(CoverageLevel.PARTIAL, dim) == Priority.MEDIUM
            assert resolve_priority(CoverageLevel.MISSING, dim) == Priority.HIGH


class _FakeCombined:
    """Mimics the schema-validated combined LLM output.

    The fixture is internally consistent with the deterministic coverage
    ladder: only a Covered verdict reports a named-body mechanism (a Partial
    verdict reporting one would be deterministically raised to Covered by
    R2, which is exactly what the raise tests assert).
    """

    def __init__(self, coverage="Covered", acknowledged=True, mechanisms=None):
        self.dimension = "Transparency"
        self.coverage = coverage
        self.gap_detected = coverage != "Covered"
        self.reason_flagged = "" if coverage == "Covered" else "No transparency provisions found"
        self.coverage_reasoning = "" if coverage == "Covered" else "Document never mentions transparency"
        self.coverage_example = "The document establishes a National AI Ethics Board and mandates annual explainability reporting" if coverage == "Covered" else ""
        self.principle_acknowledged = acknowledged
        if mechanisms is None:
            mechanisms = ["National AI Ethics Board (named body)"] if coverage == "Covered" else []
        self.operational_mechanisms = mechanisms
        self.document_evidence = []
        self.framework_evidence = []
        self.recommendations = [] if coverage == "Covered" else ["rec1", "rec2"]
        self.priority = "" if coverage == "Covered" else "High"
        self.future_strengthening_opportunities = [
            "Extend annual report to model cards"
        ] if coverage == "Covered" else []
        self.international_examples = []
        self.international_standard_reference = "OECD Catalogue of Tools and Metrics for Trustworthy AI"
        self.framework_synthesis = "The policy aligns with OECD expectations..."
        self.standard_citations = []


class TestCoverageTierEnforcement:
    """Code enforces the tier via the coverage field — the LLM cannot choose
    whether a dimension shows Recommendations or Best Practices."""

    def _analyzer(self, store) -> GapAnalyzer:
        a = GapAnalyzer.__new__(GapAnalyzer)
        a.vector_store = store
        a.nli_verifier = None
        a.provider = _FakeCombined  # only accessed by the mocked generate path
        return a

    def _run(self, monkeypatch, coverage, acknowledged=True, mechanisms=None):
        import src.gap_analyzer as ga

        def _fake_generate(**kwargs):
            return _FakeCombined(
                coverage=coverage, acknowledged=acknowledged, mechanisms=mechanisms,
            )

        monkeypatch.setattr(ga, "generate_with_retry", _fake_generate)

        from src.retrieval import ModuleRetrievalResult
        analyzer = self._analyzer(FakeVectorStore())
        retrieval = ModuleRetrievalResult(
            dimension="Transparency",
            document_chunks=[{"chunk_id": "d1", "text": "doc text", "module_role": "document"}],
            module1_chunks=[{"chunk_id": "n1", "text": "norm text", "module_role": "module_1_normative"}],
            module2_chunks=[{"chunk_id": "p1", "text": "prac text", "module_role": "module_2_practical"}],
        )
        retrieval.total_chunks = 3
        return analyzer._analyze_dimension_combined("Transparency", retrieval)

    def test_covered_forces_best_practices_and_no_recommendations(self, monkeypatch):
        gap = self._run(monkeypatch, "Covered")
        m2 = gap.module_2
        assert m2 is not None
        # Priority omitted (null) — nothing to prioritise.
        assert m2.priority is None
        # Recommendations force-empty even if the model produced them.
        assert m2.recommendations == []
        assert m2.best_practices is not None
        assert m2.best_practices.opening == BEST_PRACTICES_OPENING
        assert m2.best_practices.future_strengthening_opportunities == [
            "Extend annual report to model cards"
        ]
        assert gap.module_1.coverage_example != ""
        assert gap.module_1.coverage == CoverageLevel.COVERED
        # Legacy fields reflect the covered tier (no gap content).
        assert gap.recommendation == ""
        assert gap.un_recommendation == ""

    def test_partial_keeps_recommendations_and_priority(self, monkeypatch):
        gap = self._run(monkeypatch, "Partial")
        m2 = gap.module_2
        assert m2 is not None
        assert m2.recommendations == ["rec1", "rec2"]
        # Deterministic code priority (Medium), NOT the LLM's "High".
        assert m2.priority == Priority.MEDIUM
        assert m2.best_practices is None
        assert gap.module_1.coverage_example == ""
        assert gap.module_1.coverage == CoverageLevel.PARTIAL
        assert gap.recommendation == "rec1\nrec2"

    def test_missing_keeps_recommendations_with_high_priority(self, monkeypatch):
        # Not acknowledged + no mechanisms → the ladder does not raise a
        # genuine Missing (R1 requires acknowledgment, R2 a commitment).
        gap = self._run(monkeypatch, "Missing", acknowledged=False)
        m2 = gap.module_2
        assert m2 is not None
        assert m2.recommendations == ["rec1", "rec2"]
        assert m2.priority == Priority.HIGH
        assert m2.best_practices is None

    def test_partial_with_named_mechanism_is_raised_to_covered(self, monkeypatch):
        """Deterministic ladder enforcement: a Partial verdict whose document
        reports a named-body mechanism is an implementation commitment
        (Level 3) → raised to Covered → Best Practices tier replaces
        Recommendations, and the rule is visible in the reasoning."""
        gap = self._run(
            monkeypatch, "Partial",
            mechanisms=["National AI Ethics Board with quarterly public reporting (named body)"],
        )
        assert gap.module_1.coverage == CoverageLevel.COVERED
        # User-facing text, not the internal "R2" rule label — see
        # plain_language_ladder_note.
        assert "Raised from Partial to Covered" in gap.module_1.coverage_reasoning
        assert gap.module_2.best_practices is not None
        assert gap.module_2.recommendations == []
        assert gap.module_2.priority is None
        assert gap.module_1.gap_detected is False

    def test_covered_never_carries_best_practices_for_gap_tiers(self, monkeypatch):
        # Even if the model mistakenly emits strengthening opportunities for a
        # Partial dimension, code must drop them (best_practices is None).
        gap = self._run(monkeypatch, "Partial")
        assert gap.module_2.best_practices is None

    def test_international_examples_ungrounded_are_dropped(self, monkeypatch):
        """Anti-fabrication: an example with a chunk_id that does not exist in
        the vector store must never surface as a real practice."""
        import src.gap_analyzer as ga

        class _WithExample:
            pass

        combined = _FakeCombined(coverage="Covered")
        combined.international_examples = [
            {
                "practice": "Canada mandates AIA before high-impact deployment",
                "country_or_source": "Canada",
                "chunk_id": "does-not-exist-1234",
                "quote": "mandatory algorithmic impact assessment",
            }
        ]

        def _fake_generate(**kwargs):
            return combined

        monkeypatch.setattr(ga, "generate_with_retry", _fake_generate)

        from src.retrieval import ModuleRetrievalResult
        analyzer = self._analyzer(FakeVectorStore())
        retrieval = ModuleRetrievalResult(
            dimension="Transparency",
            document_chunks=[{"chunk_id": "d1", "text": "doc text", "module_role": "document"}],
            module1_chunks=[{"chunk_id": "n1", "text": "norm text", "module_role": "module_1_normative"}],
            module2_chunks=[{"chunk_id": "p1", "text": "prac text", "module_role": "module_2_practical"}],
        )
        retrieval.total_chunks = 3
        gap = analyzer._analyze_dimension_combined("Transparency", retrieval)
        assert gap.module_2.best_practices is not None
        assert gap.module_2.best_practices.international_examples == []


class TestGroundModule3Citations:
    """Dimension-grounding gate for Module 3 implementation citations.

    A Module 3 citation whose chunk is not topically about the dimension is
    dropped (verified-but-irrelevant is worse than honest absence), the slots
    are re-filled deterministically from dimension-topical chunks in the
    retrieved pool, and document-sourced citations are source-normalized so
    they render instead of being hidden by the framework default.
    """

    class _Store:
        def __init__(self, chunks: dict[str, dict]):
            self.chunks = chunks

        def get_chunk(self, chunk_id: str):
            return self.chunks.get(chunk_id)

    def _analyzer(self, store) -> GapAnalyzer:
        a = GapAnalyzer.__new__(GapAnalyzer)
        a.vector_store = store
        return a

    @staticmethod
    def _cit(
        chunk_id: str = "",
        quote: str = "",
        source: str = "AI Verify Assurance Pilot",
        verified: bool = False,
        no_citation: bool = False,
    ) -> ModuleCitation:
        return ModuleCitation(
            quote=quote,
            chunk_id=chunk_id,
            source=source,
            source_type="framework",
            verified=verified,
            no_citation=no_citation,
            verification=(
                {"passed": False, "method": "no_citation_available"}
                if no_citation
                else {"passed": False}
            ),
        )

    def test_off_topic_llm_citation_is_dropped(self):
        store = self._Store({
            "off1": {
                "text": "Start with a comprehensive GenAI risk assessment framework",
                "metadata": {"framework": "AI Verify Assurance Pilot"},
            },
        })
        a = self._analyzer(store)
        out = a._ground_module3_citations(
            [self._cit("off1", "generic quote", verified=True)],
            [],
            "Environmental Sustainability",
            phases_count=2,
        )
        # Generic risk-assessment boilerplate is not environmental evidence.
        assert out == []

    def test_topical_pool_chunk_attached_as_fallback(self):
        store = self._Store({
            "top1": {
                "text": (
                    "Developers of AI systems shall report annual energy "
                    "consumption to the Ministry, and the adoption of "
                    "smaller, resource-efficient models is required to "
                    "reduce environmental impact."
                ),
                "metadata": {
                    "document_name": "AI Governance India",
                    "page_number": 15,
                },
            },
        })
        a = self._analyzer(store)
        out = a._ground_module3_citations(
            [],
            [{"chunk_id": "top1", "text": store.chunks["top1"]["text"]}],
            "Environmental Sustainability",
            phases_count=2,
        )
        assert len(out) == 1
        assert out[0].chunk_id == "top1"
        assert out[0].source == "AI Governance India"
        assert out[0].source_type == "document"
        assert out[0].verified is False
        assert out[0].verification["method"] == "deterministic_fallback"

    def test_topical_llm_citation_is_kept(self):
        store = self._Store({
            "env1": {
                "text": "The policy mandates carbon footprint reporting for model training.",
                "metadata": {"framework": "OECD AI Principles"},
            },
        })
        a = self._analyzer(store)
        out = a._ground_module3_citations(
            [self._cit("env1", "carbon reporting quote", verified=True)],
            [],
            "Environmental Sustainability",
            phases_count=2,
        )
        assert len(out) == 1
        assert out[0].verified is True  # kept as-is, not re-marked

    def test_honest_decline_is_kept(self):
        a = self._analyzer(self._Store({}))
        out = a._ground_module3_citations(
            [self._cit(no_citation=True)],
            [],
            "Environmental Sustainability",
            phases_count=2,
        )
        assert len(out) == 1
        assert out[0].no_citation is True

    def test_doc_citation_source_is_normalized(self):
        # LLM cited a DOC chunk; verify path left source empty (framework
        # default). The gate must restore the document name so it renders.
        store = self._Store({
            "doc1": {
                "text": "Environmental sustainability principles for AI development.",
                "metadata": {"document_name": "AI Governance India", "page_number": 15},
            },
        })
        a = self._analyzer(store)
        out = a._ground_module3_citations(
            [self._cit("doc1", "env passage", source="", verified=True)],
            [],
            "Environmental Sustainability",
            phases_count=2,
        )
        assert len(out) == 1
        assert out[0].source == "AI Governance India"
        assert out[0].source_type == "document"
        assert out[0].document_name == "AI Governance India"

    def test_toc_preamble_chunk_is_skipped_in_topup(self):
        # A table-of-contents fragment passes the loose keyword gate (a
        # chapter title mentions the topic) but carries no evidence content.
        store = self._Store({
            "toc1": {
                "text": (
                    "Table of Contents\nTitle Page\nExecutive Summary 00\n"
                    "Chapter 1 - Introduction 01\nEnvironmental Impact 12\n"
                ),
                "metadata": {"framework": "AI Verify Assurance Pilot"},
            },
            "env1": {
                "text": "The policy mandates carbon footprint reporting for model training.",
                "metadata": {"framework": "OECD AI Principles"},
            },
        })
        a = self._analyzer(store)
        out = a._ground_module3_citations(
            [],
            [
                {"chunk_id": "toc1", "text": store.chunks["toc1"]["text"]},
                {"chunk_id": "env1", "text": store.chunks["env1"]["text"]},
            ],
            "Environmental Sustainability",
            phases_count=2,
        )
        assert [c.chunk_id for c in out] == ["env1"]

    def test_pool_chunk_without_named_source_is_skipped(self):
        store = self._Store({
            "anon1": {
                "text": "Environmental measures reduce emissions and energy use.",
                "metadata": {},
            },
        })
        a = self._analyzer(store)
        out = a._ground_module3_citations(
            [],
            [{"chunk_id": "anon1", "text": store.chunks["anon1"]["text"]}],
            "Environmental Sustainability",
            phases_count=2,
        )
        assert out == []  # never attach a citation without a named source

    def test_successful_topup_replaces_declines(self):
        # The LLM honestly declined, but the pool has a dimension-topical
        # chunk: the top-up supersedes the decline (showing both "no passage
        # found" and a citation would contradict itself).
        store = self._Store({
            "env1": {
                "text": "The policy mandates carbon footprint reporting for model training.",
                "metadata": {"framework": "OECD AI Principles"},
            },
        })
        a = self._analyzer(store)
        out = a._ground_module3_citations(
            [self._cit(no_citation=True)],
            [{"chunk_id": "env1", "text": store.chunks["env1"]["text"]}],
            "Environmental Sustainability",
            phases_count=2,
        )
        assert len(out) == 1
        assert out[0].chunk_id == "env1"
        assert out[0].no_citation is False
        assert out[0].verification["method"] == "deterministic_fallback"

    def test_no_topical_pool_returns_fewer_honestly(self):
        store = self._Store({
            "off1": {
                "text": "Start with a comprehensive GenAI risk assessment framework",
                "metadata": {"framework": "AI Verify"},
            },
        })
        a = self._analyzer(store)
        out = a._ground_module3_citations(
            [],
            [{"chunk_id": "off1", "text": store.chunks["off1"]["text"]}],
            "Environmental Sustainability",
            phases_count=2,
        )
        # Nothing topical in the corpus → honest empty result, no generic fill.
        assert out == []


class TestModule2AgencyReconciliation:
    """Module 2 / Module 3 responsible-agency cross-reference.

    When Module 3's anti-fabrication gate returns "Not specified by policy"
    but Module 2's recommendations name document-grounded institutions, the
    two sections would otherwise contradict. The reconciliation appends a
    deterministic cross-reference — never inventing an assignment.
    """

    class _FakeCollection:
        def __init__(self, text: str):
            self.text = text

        def get(self, where=None, include=None):
            return {"documents": [self.text]}

    class _Store:
        def __init__(self, doc_text: str):
            self.collection = TestModule2AgencyReconciliation._FakeCollection(doc_text)

        def get_chunk(self, chunk_id: str):
            return None

    @staticmethod
    def _agency() -> str:
        return (
            "Not specified by policy — implementation responsibility should "
            "be assigned by the adopting government."
        )

    def _analyzer(self, store) -> GapAnalyzer:
        a = GapAnalyzer.__new__(GapAnalyzer)
        a.vector_store = store
        return a

    def test_names_module2_document_grounded_bodies(self):
        store = self._Store(
            "MeitY may publish a schedule to ensure compliance. The Bureau of "
            "Indian Standards develops AI standards."
        )
        a = self._analyzer(store)
        agency, grounding = a._reconcile_responsible_agency_with_module2(
            self._agency(),
            "none_identified",
            [
                "Incorporate carbon reporting into the compliance schedule to be "
                "issued by MeitY.",
                "Task standard-setting bodies such as the Bureau of Indian "
                "Standards (BIS) with developing metrics.",
            ],
            workspace_id="ws1",
        )
        assert grounding == "none_identified"
        assert "MeitY" in agency
        assert "Bureau of Indian Standards" in agency
        assert "does not assign" in agency

    def test_named_or_implied_verdict_unchanged(self):
        store = self._Store("MeitY is the nodal ministry.")
        a = self._analyzer(store)
        agency, grounding = a._reconcile_responsible_agency_with_module2(
            "Ministry of Electronics and IT",
            "document_named",
            ["Task MeitY with reporting."],
            workspace_id="ws1",
        )
        assert agency == "Ministry of Electronics and IT"
        assert grounding == "document_named"

    def test_ungrounded_name_not_referenced(self):
        store = self._Store("The policy discusses general AI governance.")
        a = self._analyzer(store)
        agency, grounding = a._reconcile_responsible_agency_with_module2(
            self._agency(),
            "none_identified",
            ["Task the Federal AI Oversight Bureau with reporting."],
            workspace_id="ws1",
        )
        assert "Federal AI Oversight Bureau" not in agency
        assert agency == self._agency()

    def test_generic_capitalized_phrase_is_not_an_institution(self):
        """Designator gate: a capitalized noun phrase that appears verbatim
        in the document ("Digital Public Infrastructure", "Generative AI")
        must NOT be surfaced as a body being tasked — only phrases containing
        an organizational designator qualify."""
        store = self._Store(
            "The policy advances Digital Public Infrastructure and Generative "
            "AI capabilities."
        )
        a = self._analyzer(store)
        agency, grounding = a._reconcile_responsible_agency_with_module2(
            self._agency(),
            "none_identified",
            [
                "Institutionalise the Digital Public Infrastructure governance "
                "roadmap.",
                "Publish guidance for Generative AI systems.",
            ],
            workspace_id="ws1",
        )
        assert "Digital Public Infrastructure" not in agency
        assert "Generative AI" not in agency
        assert agency == self._agency()

    def test_designator_phrase_is_an_institution(self):
        """A multi-word phrase CONTAINING a designator still qualifies even
        when the first word alone would be ambiguous (e.g. "Standards" as the
        final word)."""
        store = self._Store(
            "The Atomic Energy Commission publishes AI guidance."
        )
        a = self._analyzer(store)
        agency, grounding = a._reconcile_responsible_agency_with_module2(
            self._agency(),
            "none_identified",
            ["Task the Atomic Energy Commission with developing metrics."],
            workspace_id="ws1",
        )
        assert "Atomic Energy Commission" in agency

    def test_no_workspace_returns_unchanged(self):
        a = self._analyzer(self._Store("MeitY is named in the document."))
        agency, grounding = a._reconcile_responsible_agency_with_module2(
            self._agency(),
            "none_identified",
            ["Task MeitY with reporting."],
            workspace_id="",
        )
        assert agency == self._agency()


class TestEstimatePhaseTimelines:
    """Deterministic implementation-timeline estimator — the LLM never
    decides how long implementation takes. Ranges are derived in code from
    coverage tier, existing mechanisms, maturity, agency grounding, scope.
    """

    def test_missing_without_mechanisms_is_longest(self):
        t = estimate_phase_timelines(
            coverage=CoverageLevel.MISSING,
            operational_mechanisms=[],
            maturity=GovernanceMaturity.UNADDRESSED,
            agency_grounding="none_identified",
            step_counts=[3, 3],
        )
        assert len(t) == 2
        # Missing + low maturity + no agency + no mechanisms → long Phase 1.
        assert t[0]["timeline"].startswith("0-")
        p1_upper = int(t[0]["timeline"].split("-")[1].split()[0])
        assert p1_upper >= 12
        # Phase 2 chains after Phase 1.
        p2_lo = int(t[1]["timeline"].split("-")[0])
        assert p2_lo == p1_upper
        # Reasoning explains the estimate (auditable, not magic).
        assert "Phase 1 establishes the foundation" in t[0]["reasoning"]
        assert "Missing tier" in t[0]["reasoning"]
        assert "no responsible agency named" in t[0]["reasoning"]

    def test_partial_with_mechanisms_and_named_agency_is_shortest(self):
        t = estimate_phase_timelines(
            coverage=CoverageLevel.PARTIAL,
            operational_mechanisms=["National AI Ethics Board (named body)", "Annual transparency report"],
            maturity=GovernanceMaturity.ESTABLISHED,
            agency_grounding="document_named",
            step_counts=[2, 2],
        )
        p1_upper = int(t[0]["timeline"].split("-")[1].split()[0])
        # Partial + existing mechanisms + high maturity + named agency + small
        # scope → shorter than the Missing baseline (12).
        assert p1_upper < 12
        assert "Partial tier" in t[0]["reasoning"]
        assert "existing operational mechanism" in t[0]["reasoning"]
        assert "responsible agency already named" in t[0]["reasoning"]

    def test_missing_always_longer_than_partial_ceteris_paribus(self):
        common = dict(
            operational_mechanisms=[],
            maturity=GovernanceMaturity.DEVELOPING,
            agency_grounding="document_implied",
            step_counts=[3, 3],
        )
        missing = estimate_phase_timelines(coverage=CoverageLevel.MISSING, **common)
        partial = estimate_phase_timelines(coverage=CoverageLevel.PARTIAL, **common)
        m_upper = int(missing[1]["timeline"].split("-")[1].split()[0])
        p_upper = int(partial[1]["timeline"].split("-")[1].split()[0])
        assert m_upper > p_upper

    def test_large_scope_widens_timeline(self):
        small = estimate_phase_timelines(
            coverage=CoverageLevel.PARTIAL, operational_mechanisms=[],
            maturity=GovernanceMaturity.DEVELOPING, agency_grounding="document_implied",
            step_counts=[2, 2],
        )
        large = estimate_phase_timelines(
            coverage=CoverageLevel.PARTIAL, operational_mechanisms=[],
            maturity=GovernanceMaturity.DEVELOPING, agency_grounding="document_implied",
            step_counts=[6, 6],
        )
        assert int(large[0]["timeline"].split("-")[1].split()[0]) > int(
            small[0]["timeline"].split("-")[1].split()[0]
        )
        assert "large scope" in large[0]["reasoning"]

    def test_reasoning_mentions_maturity_adjustment(self):
        t = estimate_phase_timelines(
            coverage=CoverageLevel.MISSING, operational_mechanisms=[],
            maturity=GovernanceMaturity.EMERGING, agency_grounding="none_identified",
            step_counts=[4, 4],
        )
        assert "low maturity (Emerging)" in t[0]["reasoning"]

    def test_returns_one_timeline_per_phase_up_to_two(self):
        t = estimate_phase_timelines(
            coverage=CoverageLevel.PARTIAL, operational_mechanisms=[],
            maturity=GovernanceMaturity.DEVELOPING, agency_grounding="document_implied",
            step_counts=[3],
        )
        # One entry per phase present (single-phase roadmaps stay valid).
        assert len(t) == 1
        assert t[0]["timeline"] != ""
        assert "Phase 1" in t[0]["reasoning"]
        both = estimate_phase_timelines(
            coverage=CoverageLevel.PARTIAL, operational_mechanisms=[],
            maturity=GovernanceMaturity.DEVELOPING, agency_grounding="document_implied",
            step_counts=[3, 3],
        )
        assert len(both) == 2
        assert both[1]["timeline"] != ""
        assert "Phase 2" in both[1]["reasoning"]

    def test_agency_designation_cost_applies_phase1_only(self):
        # Agency designation is a one-time Phase 1 set-up: the +3 cost lands
        # in Phase 1 reasoning only. Phase 2 chains after Phase 1 (its lower
        # bound == Phase 1's upper bound), so the designation time propagates
        # through the chain without being double-counted.
        t = estimate_phase_timelines(
            coverage=CoverageLevel.PARTIAL, operational_mechanisms=[],
            maturity=GovernanceMaturity.DEVELOPING, agency_grounding="none_identified",
            step_counts=[3, 3],
        )
        assert "no responsible agency named" in t[0]["reasoning"]
        assert "no responsible agency named" not in t[1]["reasoning"]
        p1_upper = int(t[0]["timeline"].split("-")[1].split()[0])
        p2_lo = int(t[1]["timeline"].split("-")[0])
        assert p2_lo == p1_upper


class _FakeModule34:
    """Mimics the schema-validated Module 3+4 combined LLM output — with the
    bogus echoed timeline this feature removes ("0-12 months")."""

    def __init__(self):
        self.phases = [
            {"phase": "Phase 1", "timeline": "0-12 months", "objective": "Establish foundation", "steps": ["s1", "s2", "s3"]},
            {"phase": "Phase 2", "timeline": "12-24 months", "objective": "Operationalise", "steps": ["s4", "s5", "s6"]},
        ]
        self.responsible_agency = "A plausible-sounding agency"
        self.responsible_agency_grounding = "none_identified"
        self.documentation_requirements = ["doc1"]
        self.monitoring_checklist = ["mon1"]
        self.implementation_citations = []
        self.incident_matches = []
        self.matched = False

    def model_dump_json(self) -> str:
        return '{"dimension": "Privacy"}'


class TestModule34TimelineOverride:
    """Contract lock: the LLM's timeline output can NEVER leak into the report.
    _analyze_module34_combined must always override it with the deterministic
    estimator, even when the model echoes the prompt's example ranges."""

    def _analyzer(self, store) -> GapAnalyzer:
        a = GapAnalyzer.__new__(GapAnalyzer)
        a.vector_store = store
        a.nli_verifier = None
        a.provider = object()  # only accessed by the mocked generate path
        return a

    def _run_module34(self, monkeypatch, coverage="Partial", mechanisms=None):
        import src.gap_analyzer as ga
        from src.models import Module1Evaluation
        from src.retrieval import Module34RetrievalResult

        def _fake_generate(**kwargs):
            return _FakeModule34()

        monkeypatch.setattr(ga, "generate_with_retry", _fake_generate)

        gap = make_gap("Privacy", coverage)
        gap.governance_maturity = GovernanceMaturity.EMERGING
        gap.module_1 = Module1Evaluation(
            dimension="Privacy",
            coverage=CoverageLevel(coverage),
            gap_detected=True,
            operational_mechanisms=mechanisms or [],
            governance_maturity=GovernanceMaturity.EMERGING,
        )
        retrieval = Module34RetrievalResult(
            dimension="Privacy",
            module3_chunks=[],
            module4_chunks=[],
            document_chunks=[],
        )
        analyzer = self._analyzer(FakeVectorStore())
        analyzer._analyze_module34_combined("Privacy", gap, retrieval)
        return gap

    def test_llm_timeline_never_leaks_into_phases(self, monkeypatch):
        gap = self._run_module34(
            monkeypatch, coverage="Partial", mechanisms=["Annual privacy report"],
        )
        assert gap.module_3 is not None
        assert len(gap.module_3.phases) == 2
        # The fake model echoed "0-12 months" / "12-24 months" — neither may
        # survive into the report.
        for ph in gap.module_3.phases:
            assert ph.timeline not in ("0-12 months", "12-24 months")
        # The final timelines equal the deterministic estimator run on the
        # same inputs (coverage, mechanisms, maturity, agency grounding).
        # Step counts are derived from the ACTUAL phases so the assertion
        # stays coupled to the real contract, not a hardcoded duplicate.
        expected = estimate_phase_timelines(
            coverage=CoverageLevel.PARTIAL,
            operational_mechanisms=["Annual privacy report"],
            maturity=GovernanceMaturity.EMERGING,
            agency_grounding="none_identified",
            step_counts=[len(p.steps) for p in gap.module_3.phases],
        )
        for ph, exp in zip(gap.module_3.phases, expected):
            assert ph.timeline == exp["timeline"]
            assert ph.timeline_reasoning == exp["reasoning"]
        # The honest agency state (verified) flows into the reasoning.
        assert "no responsible agency named" in gap.module_3.phases[0].timeline_reasoning

    def test_module4_absent_without_grounded_incident(self, monkeypatch):
        # No incident chunks were retrieved, so Module 4 must report the
        # honest unmatched state, not a fabricated match.
        gap = self._run_module34(monkeypatch, coverage="Missing")
        assert gap.module_4 is not None
        assert gap.module_4.matched is False
        assert gap.module_4.incident_matches == []


class TestBuildFrameworkSynthesis:
    def test_empty_positions_returns_empty(self):
        result = build_framework_synthesis([], [])
        assert result == ""

    def test_unknown_chunk_omitted(self):
        from src.models import FrameworkPositionRaw
        positions = [
            FrameworkPositionRaw(framework="OECD", position="requires X", chunk_id="nonexistent", supporting_text="X")
        ]
        evidence = [
            RetrievedEvidence(chunk_id="real1", text="t", source_framework="OECD", similarity_score=0.8)
        ]
        result = build_framework_synthesis(positions, evidence)
        assert result == ""

    def test_valid_position_included(self):
        from src.models import FrameworkPositionRaw
        positions = [
            FrameworkPositionRaw(framework="OECD AI Principles", position="requires transparency", chunk_id="c1", supporting_text="organisations should provide meaningful information")
        ]
        evidence = [
            RetrievedEvidence(chunk_id="c1", text="organisations should provide meaningful information", source_framework="OECD AI Principles", similarity_score=0.8)
        ]
        result = build_framework_synthesis(positions, evidence)
        assert "OECD AI Principles" in result
        assert "requires transparency" in result

    def test_multiple_frameworks_joined(self):
        from src.models import FrameworkPositionRaw
        positions = [
            FrameworkPositionRaw(framework="OECD AI Principles", position="requires transparency", chunk_id="c1", supporting_text="text a"),
            FrameworkPositionRaw(framework="UNESCO", position="emphasizes ethics", chunk_id="c2", supporting_text="text b"),
        ]
        evidence = [
            RetrievedEvidence(chunk_id="c1", text="text a", source_framework="OECD AI Principles", similarity_score=0.8),
            RetrievedEvidence(chunk_id="c2", text="text b", source_framework="UNESCO", similarity_score=0.8),
        ]
        result = build_framework_synthesis(positions, evidence)
        assert "OECD AI Principles" in result
        assert "UNESCO" in result

    def test_duplicate_frameworks_deduplicated(self):
        from src.models import FrameworkPositionRaw
        positions = [
            FrameworkPositionRaw(framework="OECD AI Principles", position="requires transparency", chunk_id="c1", supporting_text="text a"),
            FrameworkPositionRaw(framework="OECD AI Principles", position="also requires accountability", chunk_id="c2", supporting_text="text b"),
        ]
        evidence = [
            RetrievedEvidence(chunk_id="c1", text="text a", source_framework="OECD AI Principles", similarity_score=0.8),
            RetrievedEvidence(chunk_id="c2", text="text b", source_framework="OECD AI Principles", similarity_score=0.8),
        ]
        result = build_framework_synthesis(positions, evidence)
        assert len(result.split("|")) == 1


class TestCoveredSynthesisFallback:
    """A Covered verdict must never ship without the 'why this is compliant'
    framework comparison — when the LLM leaves framework_synthesis empty, the
    deterministic fallback names the retrieved frameworks and grounds the
    compliance claim in the document's own provisions."""

    def test_fallback_names_retrieved_frameworks(self):
        consensus, differences, overall = GapAnalyzer._build_covered_synthesis_fallback(
            dimension="Transparency",
            module1_chunks=[
                {"chunk_id": "c1", "text": "t", "source_framework": "OECD AI Principles"},
                {"chunk_id": "c2", "text": "t", "source_framework": "OECD AI Principles"},
                {"chunk_id": "c3", "text": "t", "source_framework": "UNESCO"},
            ],
            coverage_example=(
                "The document mandates annual transparency reporting and a "
                "National AI Ethics Board."
            ),
            operational_mechanisms=[],
        )
        assert "OECD AI Principles" in consensus
        assert "UNESCO" in consensus
        assert "Transparency" in consensus
        assert differences.strip()
        assert "already satisfies" in overall
        assert "annual transparency reporting" in overall
        # No gap-filling language — must never trip the synthesis-drift guard.
        for banned in ("should", "would", "will", "recommend", "adopt"):
            assert banned not in (consensus + differences + overall).lower()

    def test_fallback_uses_mechanisms_when_no_example(self):
        _, _, overall = GapAnalyzer._build_covered_synthesis_fallback(
            dimension="Privacy",
            module1_chunks=[],
            coverage_example="",
            operational_mechanisms=["Data Protection Board (named body)", "Annual privacy audit"],
        )
        assert "Data Protection Board (named body)" in overall

    def test_fallback_handles_no_provisions(self):
        _, _, overall = GapAnalyzer._build_covered_synthesis_fallback(
            dimension="Safety",
            module1_chunks=[],
            coverage_example="",
            operational_mechanisms=[],
        )
        assert "the document's stated commitments" in overall

    def test_fallback_singular_provision_stays_grammatical(self):
        # A single provision must not produce a subject-verb mismatch
        # ("...Board give the Transparency principle..."). The em-dash
        # appositive framing keeps the sentence grammatical for one item or a
        # semicolon-joined list.
        _, _, overall = GapAnalyzer._build_covered_synthesis_fallback(
            dimension="Accountability",
            module1_chunks=[],
            coverage_example="The policy names the National AI Ethics Board.",
            operational_mechanisms=[],
        )
        assert "give the Accountability principle" not in overall
        assert "National AI Ethics Board" in overall
        assert overall.strip().endswith("requirement.")


class TestClusterCompoundingExcludesUnanalysedDimensions:
    """An unanalysed dimension must not masquerade as a governance gap.

    compute_risk / resolve_priority escalate when a related dimension is also
    weak. The test was `coverage != COVERED`, which is true for
    INSUFFICIENT_EVIDENCE — the value set when a dimension fails on quota or
    provider error. Partial-failure runs therefore inflated the risk and
    priority of every surviving dimension in the cluster, reporting a policy
    as higher-risk because the pipeline broke.
    """

    @staticmethod
    def _gap(dimension, coverage, error=None):
        from src.models import GovernanceGap

        return GovernanceGap(
            dimension=dimension,
            coverage=coverage,
            reason_flagged="",
            recommendation="",
            analysis_error=error,
        )

    def test_failed_neighbour_does_not_escalate_risk(self):
        from src.gap_analyzer import compute_risk
        from src.models import CoverageLevel

        others = [self._gap("Accountability", CoverageLevel.INSUFFICIENT_EVIDENCE,
                            error="LLM quota exhausted")]
        risk, reason = compute_risk(CoverageLevel.PARTIAL, "Transparency", others)
        assert "same cluster" not in reason.lower()

    def test_real_gap_neighbour_still_escalates_risk(self):
        from src.gap_analyzer import compute_risk
        from src.models import CoverageLevel

        others = [self._gap("Accountability", CoverageLevel.MISSING)]
        risk, reason = compute_risk(CoverageLevel.PARTIAL, "Transparency", others)
        assert "same cluster" in reason.lower()

    def test_failed_neighbour_does_not_escalate_priority(self):
        from src.gap_analyzer import resolve_priority
        from src.models import CoverageLevel, Priority

        others = [self._gap("Accountability", CoverageLevel.INSUFFICIENT_EVIDENCE,
                            error="LLM quota exhausted")]
        assert resolve_priority(CoverageLevel.PARTIAL, "Transparency", others) == Priority.MEDIUM

    def test_real_gap_neighbour_still_escalates_priority(self):
        from src.gap_analyzer import resolve_priority
        from src.models import CoverageLevel, Priority

        others = [self._gap("Accountability", CoverageLevel.MISSING)]
        assert resolve_priority(CoverageLevel.PARTIAL, "Transparency", others) == Priority.HIGH


class TestMaturityIndexCalibration:
    """The composite index scores STAGES, not ordinal ranks.

    `100 * sum(ranks) / (3 * n)` treats the four stages as an interval scale,
    which asserts that moving from Unaddressed to Emerging is worth exactly as
    much as moving from Operationalized to Institutionalized. MATURITY_RANK's
    own comment forbids averaging the ranks; the index did it anyway.
    """

    @staticmethod
    def _stages(*labels):
        from src.gap_analyzer import MATURITY_STAGE_SCORE
        from src.models import GovernanceMaturity
        by_name = {
            "U": GovernanceMaturity.UNADDRESSED,
            "E": GovernanceMaturity.EMERGING,
            "O": GovernanceMaturity.DEVELOPING,
            "I": GovernanceMaturity.ESTABLISHED,
        }
        stages = [by_name[x] for x in labels]
        return round(sum(MATURITY_STAGE_SCORE[s] for s in stages) / len(stages), 1)

    def test_scores_are_monotonic_across_stages(self):
        from src.gap_analyzer import MATURITY_STAGE_SCORE, MATURITY_RANK
        ordered = sorted(MATURITY_RANK, key=lambda s: MATURITY_RANK[s])
        scores = [MATURITY_STAGE_SCORE[s] for s in ordered]
        assert scores == sorted(scores)
        assert scores[0] == 0.0
        assert scores[-1] == 100.0

    def test_creating_a_binding_duty_is_the_largest_step(self):
        """Emerging→Operationalized is the tier ladder's central claim, so it
        must not be priced below the step above it."""
        from src.gap_analyzer import MATURITY_STAGE_SCORE as S
        from src.models import GovernanceMaturity as G
        duty_step = S[G.DEVELOPING] - S[G.EMERGING]
        enforcement_step = S[G.ESTABLISHED] - S[G.DEVELOPING]
        assert duty_step > enforcement_step

    def test_recognition_without_obligation_scores_exactly_half(self):
        """A document that names every dimension and binds nobody."""
        assert self._stages(*(["E"] * 8)) == 50.0

    def test_an_absent_dimension_contributes_nothing(self):
        assert self._stages(*(["U"] * 8)) == 0.0

    def test_live_corpus_calibration(self):
        """Measured stage profiles from the real runs. These pin the scale to
        documents rather than to intuition, so a future tweak has to justify
        moving a known instrument."""
        # EU AI Act: six Institutionalized, one Operationalized, one Emerging.
        assert self._stages("I", "I", "I", "I", "I", "O", "I", "E") == 91.0
        # Japan, all three instruments read together.
        assert self._stages("O", "I", "I", "O", "E", "E", "I", "E") == 75.8
        # Japan's voluntary guidelines alone.
        assert self._stages("E", "E", "O", "O", "E", "E", "E", "E") == 57.0

    def test_binding_regulation_clearly_outscores_soft_law(self):
        """Differentiation is the point of the whole scoring system; the
        gentler scale must not compress it away."""
        eu = self._stages("I", "I", "I", "I", "I", "O", "I", "E")
        soft = self._stages("E", "E", "O", "O", "E", "E", "E", "E")
        assert eu - soft > 30
