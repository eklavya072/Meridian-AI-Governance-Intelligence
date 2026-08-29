"""Tests for governance evidence-strength scoring.

Every case here is drawn from a real passage in the ingested corpora that the
previous keyword ladder scored wrongly — these are regression tests for
concrete misclassifications, not synthetic examples.
"""

from src.evidence_strength import (
    TIER_ASPIRATIONAL,
    TIER_ASSIGNED,
    TIER_ENFORCEABLE,
    TIER_INTENTIONAL,
    TIER_OBLIGATORY,
    EvidenceProfile,
    build_profile,
    classify_sentence,
    coverage_from_profile,
    detect_nonbinding_document,
    is_structural_noise,
    is_third_party_attribution,
    maturity_from_profile,
)


class TestNormativeTiers:
    def test_binding_duty_on_regulated_party_is_obligatory(self):
        s = classify_sentence(
            "Providers of high-risk AI systems shall ensure that their systems "
            "are compliant with the requirements set out in Section 2."
        )
        assert s.tier == TIER_OBLIGATORY
        assert s.duty_bearer == "regulated"

    def test_duty_with_consequence_is_enforceable(self):
        s = classify_sentence(
            "Providers shall report serious incidents to the authority and "
            "non-compliance is subject to penalties."
        )
        assert s.tier == TIER_ENFORCEABLE
        assert s.has_enforcement

    def test_government_directing_itself_caps_at_assigned(self):
        """A ministry instructing itself is a plan, not a duty.

        This is the rule that stops strategy implementation matrices — which
        universally pair a ministry with an activity — from outranking
        statutes that impose real duties.
        """
        s = classify_sentence(
            "The Ministry of ICT shall develop guidelines for artificial "
            "intelligence adoption across government."
        )
        assert s.tier == TIER_ASSIGNED
        assert s.duty_bearer == "government"

    def test_institution_with_authority_power_outranks_one_that_coordinates(self):
        authority = classify_sentence(
            "The Data Protection Board may investigate and impose penalties on "
            "any entity that processes personal data unlawfully."
        )
        promotion = classify_sentence(
            "The Ministry will coordinate and promote awareness of artificial "
            "intelligence across sectors."
        )
        assert authority.tier > promotion.tier
        assert authority.tier == TIER_ENFORCEABLE

    def test_modal_without_a_duty_bearer_is_aspirational(self):
        """ "AI must serve as an enabler" is a slogan wearing a modal verb."""
        s = classify_sentence(
            "Artificial intelligence must serve as an enabler of inclusive "
            "development and shared prosperity for all."
        )
        assert s.tier == TIER_ASPIRATIONAL

    def test_soft_duty_on_regulated_party_beats_bare_principle(self):
        soft_duty = classify_sentence(
            "AI business actors should improve the explainability of their "
            "systems for relevant stakeholders."
        )
        principle = classify_sentence(
            "Transparency is an important principle for artificial intelligence."
        )
        assert soft_duty.tier == TIER_INTENTIONAL
        assert principle.tier == TIER_ASPIRATIONAL

    def test_hedge_demotes_an_obligation(self):
        hard = classify_sentence("Providers shall publish an annual transparency report.")
        hedged = classify_sentence(
            "Providers shall, where feasible, publish an annual transparency report."
        )
        assert hedged.tier == hard.tier - 1

    def test_nonbinding_document_caps_provisions(self):
        s = classify_sentence(
            "Providers shall ensure that systems are auditable.",
            document_is_nonbinding=True,
        )
        assert s.tier == TIER_INTENTIONAL


class TestExclusions:
    def test_foreign_framework_attribution_is_excluded(self):
        """Kenya's retrieved Transparency evidence was entirely about Australia."""
        assert is_third_party_attribution(
            "Australia's 2021 AI Action Plan aims to build AI capability and "
            "promote trusted, secure AI technologies.",
            own_jurisdiction="Kenya",
        )

    def test_foreign_enforcement_narrative_is_excluded(self):
        """Real case: this scored as top-tier DOMESTIC governance for Kenya."""
        assert is_third_party_attribution(
            "In Canada, the Federal Office of the Privacy Commissioner and "
            "provincial privacy authorities launched an investigation into "
            "ChatGPT for processing personal data without consent.",
            own_jurisdiction="Kenya",
        )

    def test_self_reference_is_not_treated_as_foreign(self):
        assert not is_third_party_attribution(
            "This Regulation lays down harmonised rules for providers placing "
            "AI systems on the Union market.",
            own_jurisdiction="European Union",
        )

    def test_own_jurisdiction_named_is_not_foreign(self):
        assert not is_third_party_attribution(
            "Kenya will establish a national data governance framework.",
            own_jurisdiction="Kenya",
        )

    def test_contents_listing_is_structural_noise(self):
        assert is_structural_noise(
            "Practical AI Ethical Guidelines Table of Content Executive Summary "
            "Implementation Plan Summary 1 7 7 11 13 14 16 18"
        )

    def test_real_provision_is_not_structural_noise(self):
        assert not is_structural_noise(
            "The controller must notify the supervisory authority within 72 hours."
        )

    def test_nonbinding_disclaimer_detected(self):
        assert detect_nonbinding_document(
            ["These guidelines are non-binding and do not impose legal obligations."]
        )
        assert not detect_nonbinding_document(["This Regulation shall be binding in its entirety."])


class TestProfileAggregation:
    def test_overlapping_chunk_duplicates_counted_once(self):
        """Chunk overlap returned one Kenyan sentence five times, and the
        prefix-keyed dedup treated each offset as a separate provision —
        inflating a single sentence into "5 binding provisions"."""
        base = (
            "Operators shall ensure that all high-risk systems are registered "
            "with the national authority before deployment."
        )
        sentences = [base, base[6:], base[12:], "fostering " + base, base[:-5]]
        profile = build_profile(sentences)
        assert profile.n_scored == 1

    def test_pure_aspiration_never_reaches_covered(self):
        sentences = [
            "Artificial intelligence should be developed transparently for all citizens." + str(i)
            for i in range(12)
        ]
        profile = build_profile(sentences)
        coverage, _ = coverage_from_profile(profile)
        assert coverage != "Covered"

    def test_binding_regime_reaches_covered_and_institutionalized(self):
        sentences = [
            "Providers shall register high-risk systems and are subject to audit by the authority.",
            "Deployers must maintain logs and non-compliance carries penalties.",
            "The supervisory authority may inspect providers and impose sanctions.",
            "The Commission shall establish and maintain a public registry of such systems.",
        ]
        profile = build_profile(sentences)
        assert coverage_from_profile(profile)[0] == "Covered"
        assert maturity_from_profile(profile)[0] == "Institutionalized"

    def test_empty_evidence_is_missing_and_unaddressed(self):
        profile = build_profile([])
        assert coverage_from_profile(profile)[0] == "Missing"
        assert maturity_from_profile(profile)[0] == "Unaddressed"

    def test_pure_aspiration_never_reaches_covered_no_matter_how_often_repeated(self):
        """Repeating a non-binding 'should consider' sentence many times must
        NOT accumulate into Covered — there is no volume of aspiration that
        substitutes for a single binding duty.

        A "breadth" path to Covered (many commitment-tier sentences, no
        binding duty required) used to exist here and made exactly this
        pattern score Covered. It was removed after being confirmed live
        across three independent country runs (Kenya, Nigeria, EU) as an
        internal inconsistency: sibling dimensions in the SAME document,
        citing near-identical evidence, landed on Partial while whichever one
        happened to cross the repetition-count threshold got inflated to
        Covered — a verdict that tracked sentence count, not the presence of
        a duty.
        """
        sentences = [
            f"AI business actors should consider fairness in system design, case {i}."
            for i in range(10)
        ]
        profile = build_profile(sentences)
        coverage, _ = coverage_from_profile(profile)
        assert coverage != "Covered"

    def test_coverage_and_maturity_are_independent(self):
        """A dimension can be genuinely governed yet not fully institutionalized.

        The previous implementation derived maturity FROM coverage, so the two
        labels were redundant and every raised Covered verdict dragged
        maturity up with it. Two binding duties without any enforcement
        language should read as Covered (the duty exists) but only
        Operationalized (nothing backs it up yet) — Covered must not imply
        Institutionalized.
        """
        sentences = [
            "Providers shall ensure that high-risk AI systems undergo a conformity assessment before deployment.",
            "Deployers shall maintain records of every automated decision for a period of five years.",
        ]
        profile = build_profile(sentences, own_jurisdiction="Testland")
        coverage, _ = coverage_from_profile(profile)
        maturity, _ = maturity_from_profile(profile)
        assert coverage == "Covered"
        assert maturity == "Operationalized"


class TestOcrTolerance:
    def test_space_shattered_vocabulary_still_matches(self):
        """PDF extraction produced "deplo yers"/"conf or mity" — 0 intact
        occurrences of either word in a 10MB corpus."""
        s = classify_sentence(
            "Provid ers and deplo yers of high-r isk AI syste ms shall ensure "
            "conf or mity assessment is completed before placing on the market."
        )
        assert s.tier >= TIER_OBLIGATORY
        assert s.duty_bearer == "regulated"


class TestDimensionSenseDisambiguation:
    """Core terms that carry a second, unrelated sense in policy prose.

    Each case below was confirmed as a live false positive that inflated a
    real verdict before DIMENSION_TERM_EXCLUSIONS existed.
    """

    def test_transparent_financing_is_not_ai_transparency(self):
        from src.deterministic import _sentence_has_core_term

        assert not _sentence_has_core_term(
            "Respondents recommended creating transparent financing models to "
            "support startups and innovators.",
            "Transparency",
        )

    def test_genuine_transparency_still_matches(self):
        from src.deterministic import _sentence_has_core_term

        assert _sentence_has_core_term(
            "Providers shall ensure the AI system is transparent to affected "
            "individuals and explain automated decisions.",
            "Transparency",
        )

    def test_sentence_carrying_both_senses_still_matches(self):
        """Masking must remove only the off-sense phrase, not the sentence."""
        from src.deterministic import _sentence_has_core_term

        assert _sentence_has_core_term(
            "The strategy promotes transparent financing models and also "
            "requires transparency in automated decision-making by public bodies.",
            "Transparency",
        )

    def test_inclusive_growth_is_not_demographic_inclusion(self):
        from src.deterministic import _sentence_has_core_term

        assert not _sentence_has_core_term(
            "The strategy targets inclusive growth across all economic sectors.",
            "Inclusivity",
        )

    def test_fair_competition_is_not_algorithmic_fairness(self):
        from src.deterministic import _sentence_has_core_term

        assert not _sentence_has_core_term(
            "Regulators shall ensure fair competition and fair market access.",
            "Fairness",
        )

    def test_sustainable_growth_is_not_environmental_sustainability(self):
        from src.deterministic import _sentence_has_core_term

        assert not _sentence_has_core_term(
            "AI can drive sustainable growth and innovation across the economy.",
            "Environmental Sustainability",
        )

    def test_accessible_information_is_not_disability_inclusion(self):
        from src.deterministic import _sentence_has_core_term

        assert not _sentence_has_core_term(
            "Instructions shall include relevant, accessible and comprehensible "
            "information for deployers.",
            "Inclusivity",
        )


class TestMechanismDetection:
    """Mechanism-level comparison against framework-expected governance.

    This is the approach that replaced sentence-similarity framework
    alignment, which was measured and rejected for being anti-correlated with
    governance strength (see the note in evidence_strength.py). Matching on
    what a provision DOES, graded by the tier classifier, is immune to the
    writing-register confound that broke that attempt.
    """

    @staticmethod
    def _s(text, tier, bearer="regulated"):
        from src.evidence_strength import ScoredSentence

        return ScoredSentence(text, tier, bearer, tier >= 4)

    def test_word_boundary_prevents_substring_false_positive(self):
        """'liab' matched inside 're-liab-le' and scored a data-quality
        sentence as a liability-allocation mechanism."""
        from src.evidence_strength import TIER_ASPIRATIONAL, detect_mechanisms

        mech = detect_mechanisms(
            [
                self._s(
                    "Consistent and reliable data used in AI applications.",
                    TIER_ASPIRATIONAL,
                    "none",
                )
            ],
            "Accountability",
        )
        assert "liability allocation" not in mech.present

    def test_genuine_liability_provision_is_detected(self):
        from src.evidence_strength import TIER_OBLIGATORY, detect_mechanisms

        mech = detect_mechanisms(
            [
                self._s(
                    "The provider shall be liable under applicable Union liability "
                    "law for any damage caused.",
                    TIER_OBLIGATORY,
                )
            ],
            "Accountability",
        )
        assert "liability allocation" in mech.present

    def test_mechanism_inherits_the_force_of_its_provision(self):
        """The same mechanism must grade differently by how it is imposed."""
        from src.evidence_strength import (
            TIER_ASPIRATIONAL,
            TIER_OBLIGATORY,
            detect_mechanisms,
        )

        soft = detect_mechanisms(
            [
                self._s(
                    "Providers should consider explaining automated decisions.", TIER_ASPIRATIONAL
                )
            ],
            "Transparency",
        )
        hard = detect_mechanisms(
            [
                self._s(
                    "Providers shall explain automated decisions to affected persons.",
                    TIER_OBLIGATORY,
                )
            ],
            "Transparency",
        )
        assert soft.binding_met == 0
        assert hard.binding_met >= 1

    def test_absent_mechanisms_are_reported(self):
        from src.evidence_strength import TIER_ASPIRATIONAL, detect_mechanisms

        mech = detect_mechanisms(
            [
                self._s(
                    "Privacy is an important value for artificial intelligence.",
                    TIER_ASPIRATIONAL,
                    "none",
                )
            ],
            "Privacy",
        )
        assert mech.absent
        assert "consent" in mech.absent


class TestMechanismBreadthGate:
    """Force and mechanism breadth are orthogonal; Covered needs both.

    Observed live: a soft-law instrument scored Covered for Privacy on 1 of 7
    mechanisms — no consent rule, no data minimisation, no purpose limitation,
    no anonymisation, no data-subject rights — purely because one provision was
    binding and enforcement-backed.
    """

    @staticmethod
    def _strong_profile():
        return EvidenceProfile(
            dimension="Privacy",
            n_scored=12,
            n_commitment=8,
            n_institutional=6,
            n_binding=3,
            n_enforceable=2,
            max_tier=4,
        )

    def test_narrow_mechanism_coverage_holds_verdict_at_partial(self):
        from src.evidence_strength import MechanismCoverage

        mech = MechanismCoverage(
            dimension="Privacy",
            present={"data security": 4},
            absent=[
                "consent",
                "data minimisation",
                "purpose limitation",
                "anonymisation / PETs",
                "data subject rights",
                "retention limits",
            ],
        )
        coverage, note = coverage_from_profile(self._strong_profile(), mechanisms=mech)
        assert coverage == "Partial"
        assert "1 of 7" in note

    def test_broad_mechanism_coverage_allows_covered(self):
        from src.evidence_strength import MechanismCoverage

        mech = MechanismCoverage(
            dimension="Privacy",
            present={
                "consent": 3,
                "data minimisation": 3,
                "purpose limitation": 3,
                "data subject rights": 4,
            },
            absent=["anonymisation / PETs", "retention limits"],
        )
        coverage, _ = coverage_from_profile(self._strong_profile(), mechanisms=mech)
        assert coverage == "Covered"

    def test_gate_never_promotes_a_weak_document(self):
        """Full mechanism breadth with no binding force must stay below Covered."""
        from src.evidence_strength import MechanismCoverage

        weak = EvidenceProfile(
            dimension="Privacy",
            n_scored=10,
            n_commitment=6,
            n_institutional=2,
            n_binding=0,
            n_enforceable=0,
            max_tier=2,
        )
        mech = MechanismCoverage(
            dimension="Privacy",
            present={f"m{i}": 1 for i in range(7)},
            absent=[],
        )
        coverage, _ = coverage_from_profile(weak, mechanisms=mech)
        assert coverage != "Covered"

    def test_absent_mechanism_data_is_backward_compatible(self):
        coverage, _ = coverage_from_profile(self._strong_profile(), mechanisms=None)
        assert coverage == "Covered"


class TestCoverageMaturityInvariant:
    """Coverage and maturity are independent labels, but not unconstrained.

    They read the same counters, so they can contradict each other, and they
    did: a lone unenforced duty produced coverage "Partial — stands alone
    rather than forming a developed regime" alongside maturity
    "Operationalized" on the live EU AI Act run. The two ladders had drifted
    because the degenerate `n_binding >= 1` threshold was fixed on one side
    only. These tests pin the relationship for EVERY reachable counter
    combination rather than for the handful of shapes that happen to appear
    in today's corpora.
    """

    @staticmethod
    def _profile(scored, commitment, institutional, binding, enforceable):
        from src.evidence_strength import EvidenceProfile

        return EvidenceProfile(
            dimension="Test",
            n_scored=scored,
            n_commitment=commitment,
            n_institutional=institutional,
            n_binding=binding,
            n_enforceable=enforceable,
        )

    def _reachable(self):
        """Counter combinations the classifier can actually produce.

        The n_* counters are CUMULATIVE, so only monotone tuples are real:
        n_enforceable <= n_binding <= n_institutional <= n_commitment <= n_scored.
        Testing non-monotone tuples would assert behaviour on states that
        cannot occur and would fail for the wrong reason.
        """
        for scored in range(0, 6):
            for commitment in range(0, scored + 1):
                for institutional in range(0, commitment + 1):
                    for binding in range(0, institutional + 1):
                        for enforceable in range(0, binding + 1):
                            yield self._profile(
                                scored, commitment, institutional, binding, enforceable
                            )

    def test_lone_unenforced_duty_is_not_operationalized(self):
        """The exact EU Environmental Sustainability shape: binding=1,
        enforceable=0. Coverage calls it thin; maturity must agree."""
        from src.evidence_strength import coverage_from_profile, maturity_from_profile

        profile = self._profile(1, 1, 1, 1, 0)
        assert coverage_from_profile(profile)[0] == "Partial"
        assert maturity_from_profile(profile)[0] == "Delegated"

    def test_partial_coverage_never_reports_built_out_maturity(self):
        """Across every reachable profile: if the document does not govern the
        dimension (coverage below Covered), maturity cannot claim the
        governance is operating or institutionalized."""
        from src.evidence_strength import coverage_from_profile, maturity_from_profile

        built_out = {"Operationalized", "Institutionalized"}
        for profile in self._reachable():
            coverage, _ = coverage_from_profile(profile)
            maturity, _ = maturity_from_profile(profile)
            if coverage != "Covered":
                assert maturity not in built_out, (
                    f"coverage={coverage} but maturity={maturity} for "
                    f"scored={profile.n_scored} commitment={profile.n_commitment} "
                    f"institutional={profile.n_institutional} "
                    f"binding={profile.n_binding} enforceable={profile.n_enforceable}"
                )

    def test_covered_always_reports_at_least_operationalized(self):
        """The converse leak: a dimension the document genuinely governs must
        not be reported as barely emerging."""
        from src.evidence_strength import coverage_from_profile, maturity_from_profile

        for profile in self._reachable():
            coverage, _ = coverage_from_profile(profile)
            if coverage != "Covered":
                continue
            maturity, _ = maturity_from_profile(profile)
            assert maturity in {"Operationalized", "Institutionalized"}, (
                f"coverage=Covered but maturity={maturity} for "
                f"binding={profile.n_binding} enforceable={profile.n_enforceable}"
            )

    def test_unscored_dimension_is_unaddressed_on_both_ladders(self):
        from src.evidence_strength import coverage_from_profile, maturity_from_profile

        profile = self._profile(0, 0, 0, 0, 0)
        assert coverage_from_profile(profile)[0] == "Missing"
        assert maturity_from_profile(profile)[0] == "Unaddressed"

    def test_both_ladders_read_the_same_force_bar(self):
        """Guards against the two functions drifting apart again by keeping a
        single definition of 'is this governed', not two copies of it."""
        from src.evidence_strength import coverage_from_profile, meets_force_bar

        for profile in self._reachable():
            if not profile.n_scored:
                continue
            coverage, _ = coverage_from_profile(profile)
            # Coverage can be held DOWN by the mechanism gate, but it can never
            # read Covered without clearing the bar.
            if coverage == "Covered":
                assert meets_force_bar(profile)


class TestMechanismGateReachesTheVerdict:
    """The breadth gate must hold down the verdict that actually ships.

    It was wired into the pre-LLM verdict but NOT into the call whose result
    is stored, so a soft-law guideline shipped "Covered" for Privacy directly
    above "Provides 1 of 7 governance mechanisms ... Not addressed: consent,
    data minimisation, purpose limitation, anonymisation". The prompt said
    Partial, the output said Covered, about the same document.
    """

    @staticmethod
    def _mechanisms(present_n, absent_n):
        from src.evidence_strength import TIER_OBLIGATORY, MechanismCoverage

        return MechanismCoverage(
            dimension="Privacy",
            present={f"mech_{i}": TIER_OBLIGATORY for i in range(present_n)},
            absent=[f"absent_{i}" for i in range(absent_n)],
        )

    @staticmethod
    def _profile(binding, enforceable):
        from src.evidence_strength import EvidenceProfile

        return EvidenceProfile(
            dimension="Privacy",
            n_scored=binding,
            n_commitment=binding,
            n_institutional=binding,
            n_binding=binding,
            n_enforceable=enforceable,
        )

    def test_the_japan_privacy_shape_is_downgraded(self):
        """2 binding duties, no enforcement, 1 of 7 mechanisms."""
        from src.evidence_strength import coverage_from_profile

        profile = self._profile(binding=2, enforceable=0)
        # Without the gate this profile clears the force bar outright.
        assert coverage_from_profile(profile)[0] == "Covered"
        level, note = coverage_from_profile(profile, mechanisms=self._mechanisms(1, 6))
        assert level == "Partial"
        assert "1 of 7" in note

    def test_gate_never_promotes(self):
        """Full mechanism breadth cannot manufacture governing force."""
        from src.evidence_strength import coverage_from_profile

        profile = self._profile(binding=0, enforceable=0)
        profile.n_scored = 6
        profile.n_commitment = 6
        level, _ = coverage_from_profile(profile, mechanisms=self._mechanisms(7, 0))
        assert level != "Covered"

    def test_breadth_above_the_floor_is_left_alone(self):
        from src.evidence_strength import coverage_from_profile

        profile = self._profile(binding=2, enforceable=1)
        assert coverage_from_profile(profile, mechanisms=self._mechanisms(4, 1))[0] == "Covered"


class TestDelegatedStage:
    """Emerging used to absorb three materially different profiles and pay
    them all the same 50: a real binding duty, a named institution with no
    duty, and a bare principle. India's Inclusivity, Human Autonomy and
    Fairness were the live case — three different narratives, one score."""

    def _profile(self, scored, commitment, institutional, binding, enforceable):
        p = EvidenceProfile(dimension="Fairness")
        p.n_scored = scored
        p.n_commitment = commitment
        p.n_institutional = institutional
        p.n_binding = binding
        p.n_enforceable = enforceable
        return p

    def test_named_institution_outranks_bare_commitment(self):
        institution = self._profile(4, 4, 2, 0, 0)
        commitment = self._profile(4, 4, 0, 0, 0)
        assert maturity_from_profile(institution)[0] == "Delegated"
        assert maturity_from_profile(commitment)[0] == "Emerging"

    def test_lone_duty_outranks_bare_commitment(self):
        duty = self._profile(4, 4, 3, 1, 0)
        commitment = self._profile(4, 4, 0, 0, 0)
        assert maturity_from_profile(duty)[0] == "Delegated"
        assert maturity_from_profile(commitment)[0] == "Emerging"

    def test_principle_only_stays_emerging(self):
        """India's Fairness: discussed, nobody owns it, nothing binding."""
        assert maturity_from_profile(self._profile(5, 0, 0, 0, 0))[0] == "Emerging"

    def test_force_bar_is_untouched(self):
        """The whole point: Delegated must not become a back door to a
        built-out verdict. A document that binds nobody still cannot reach
        Operationalized."""
        for institutional in range(0, 6):
            p = self._profile(6, 6, institutional, 0, 0)
            assert maturity_from_profile(p)[0] in {"Emerging", "Delegated"}

    def test_delegated_ranks_between_emerging_and_operationalized(self):
        from src.gap_analyzer import MATURITY_RANK, MATURITY_STAGE_SCORE
        from src.models import GovernanceMaturity as G

        assert MATURITY_RANK[G.EMERGING] < MATURITY_RANK[G.DELEGATED] < MATURITY_RANK[G.DEVELOPING]
        assert (
            MATURITY_STAGE_SCORE[G.EMERGING]
            < MATURITY_STAGE_SCORE[G.DELEGATED]
            < MATURITY_STAGE_SCORE[G.DEVELOPING]
        )

    def test_every_stage_has_a_score(self):
        from src.gap_analyzer import MATURITY_RANK, MATURITY_STAGE_SCORE
        from src.models import GovernanceMaturity as G

        for stage in G:
            assert stage in MATURITY_STAGE_SCORE
            assert stage in MATURITY_RANK


class TestTwoAxisAnalytics:
    """Coverage breadth and binding force must move independently. The whole
    reason for two numbers is the cases where they diverge: a soft-law
    instrument addressing nearly everything and binding almost none of it, and
    a narrow statute binding hard."""

    def _gap(self, dim, maturity, present, absent):
        from src.models import CoverageLevel, GovernanceGap

        return GovernanceGap(
            dimension=dim,
            coverage=CoverageLevel.PARTIAL,
            gap_found=False,
            reason_flagged="",
            recommendation="",
            governance_maturity=maturity,
            mechanisms_present=present,
            mechanisms_absent=absent,
        )

    def test_breadth_without_force(self):
        """Soft law: every mechanism mentioned, none of them a duty."""
        from src.gap_analyzer import compute_decision_analytics
        from src.models import GovernanceMaturity as G

        gaps = [self._gap("Fairness", G.EMERGING, {"a": 1, "b": 1, "c": 1}, [])]
        a = compute_decision_analytics(gaps)
        assert a["coverage_index"] == 100.0
        assert a["binding_share"] == 0.0
        assert a["maturity_index"] == 50.0

    def test_force_without_breadth(self):
        """Narrow statute: one mechanism, but it is genuinely enforceable."""
        from src.gap_analyzer import compute_decision_analytics
        from src.models import GovernanceMaturity as G

        gaps = [self._gap("Privacy", G.ESTABLISHED, {"a": 4}, ["b", "c", "d"])]
        a = compute_decision_analytics(gaps)
        assert a["coverage_index"] == 25.0
        assert a["binding_share"] == 100.0
        assert a["maturity_index"] == 100.0

    def test_coverage_index_is_not_tier_weighted(self):
        """Weighting breadth by force would fold the force axis back into it
        and collapse the distinction the second axis exists to draw."""
        from src.gap_analyzer import compute_decision_analytics
        from src.models import GovernanceMaturity as G

        weak = [self._gap("D", G.EMERGING, {"a": 0, "b": 0}, ["c"])]
        strong = [self._gap("D", G.ESTABLISHED, {"a": 4, "b": 4}, ["c"])]
        assert (
            compute_decision_analytics(weak)["coverage_index"]
            == compute_decision_analytics(strong)["coverage_index"]
        )

    def test_no_mechanism_table_does_not_divide_by_zero(self):
        from src.gap_analyzer import compute_decision_analytics
        from src.models import GovernanceMaturity as G

        a = compute_decision_analytics([self._gap("D", G.EMERGING, {}, [])])
        assert a["coverage_index"] == 0.0
        assert a["binding_share"] == 0.0
