"""The scorer: enforcement split, scoped backing, gates and aggregation.

Every case here is drawn from a real sentence in the corpus, because each
defect was found in a real document rather than reasoned about.
"""

import pytest

from src.evidence_strength import TIER_ENFORCEABLE, TIER_OBLIGATORY
from src.grading import (
    _classify_base,
    build_provision_profile,
    classify_provision,
    detect_enforcement_regime,
    dimension_enforcement_backing,
    evidence_is_sufficient,
    strip_policing,
)


class TestEnforcementIsNotOversight:
    """The defect that inverted Egypt against Japan."""

    def test_audit_without_consequence_is_binding_but_not_enforceable(self):
        # Egypt, National Guidelines p.5 — verbatim.
        s = (
            "Institutions must adopt clarity in roles (such as Chief AI Officers), "
            "maintain audit mechanisms, and ensure continuous alignment with "
            "national regulations."
        )
        assert classify_provision(s).tier == TIER_OBLIGATORY

    def test_a_real_penalty_still_reaches_the_top_tier(self):
        s = (
            "A Data Fiduciary who breaches these provisions shall be liable to a "
            "penalty of fifty crore rupees."
        )
        assert _classify_base(s).tier == TIER_ENFORCEABLE

    def test_supervisory_power_with_a_consequence_reaches_the_top_tier(self):
        s = "The market surveillance authority may investigate and impose fines on providers."
        assert _classify_base(s).tier == TIER_ENFORCEABLE

    def test_egypt_establishes_no_enforcement_regime(self):
        """Zero penalty, fine, sanction or offence terms in 80 pages."""
        texts = [
            "Institutions must maintain audit mechanisms and internal review.",
            "An organization must implement procedures ensuring clear governance.",
            "Pre-deployment assessment: testing, evaluating and documenting systems.",
            "Organizations should conduct a comprehensive self assessment checklist.",
        ]
        assert detect_enforcement_regime(texts) is False


class TestPolicingIsNotEnforcement:
    """One sentence about the police was lifting a whole verdict."""

    def test_law_enforcement_is_masked(self):
        assert "enforcement" not in strip_policing("strengthen law enforcement capacity").lower()
        assert "enforcement" not in strip_policing("law-enforcement agencies").lower()

    def test_kenyas_only_top_tier_sentence_was_about_the_police(self):
        # Kenya National AI Strategy — the single T4 sentence in 144 pages.
        s = (
            "At the same time, the government will strengthen law enforcement, "
            "improve regulatory effectiveness, and ensure implementation of laws."
        )
        assert classify_provision(s).tier < TIER_OBLIGATORY

    def test_enforcing_the_instrument_still_counts(self):
        s = "Providers shall be subject to enforcement action and penalties for breach."
        assert _classify_base(s).tier == TIER_ENFORCEABLE


class TestEnforcementBackingIsScopedToTheDocument:
    """Japan's 2003 privacy statute was backing Fairness and Transparency."""

    def test_a_statute_backs_only_dimensions_it_supplies_duties_to(self):
        by_doc = {
            "APPI 2003.pdf": ["A business handling personal information must obtain consent."],
            "AI Guidelines for Business.pdf": ["Business actors should consider fairness."],
        }
        assert dimension_enforcement_backing(by_doc, {"APPI 2003.pdf"}, "Privacy") is True

    def test_a_document_with_no_binding_sentence_here_lends_nothing(self):
        by_doc = {"AI Guidelines for Business.pdf": ["Business actors should consider fairness."]}
        assert dimension_enforcement_backing(by_doc, {"APPI 2003.pdf"}, "Fairness") is False

    def test_no_regime_anywhere_means_no_backing(self):
        by_doc = {"Strategy.pdf": ["Providers shall publish a register of systems."]}
        assert dimension_enforcement_backing(by_doc, set(), "Transparency") is False


class TestEvidenceSufficiencyGate:
    """Evidence sufficiency: the threshold is derived from the corpus, not chosen.

    Binding sentences are 18.2% of scored sentences in cells that carry a
    duty, so 0.818^8 = 0.19 — below that, "no duty found" in a SAMPLE is worth
    less than 80% confidence. The profile is now a census of the whole
    document, so the threshold grades how much text a verdict describes rather
    than withholding it.
    """

    def test_the_threshold_matches_its_stated_derivation(self):
        from src.grading import (
            EVIDENCE_BASE_RATE,
            EVIDENCE_CONFIDENCE,
            MIN_SCORED_FOR_ABSENCE,
        )

        miss = (1 - EVIDENCE_BASE_RATE) ** MIN_SCORED_FOR_ABSENCE
        assert miss <= 1 - EVIDENCE_CONFIDENCE
        one_fewer = (1 - EVIDENCE_BASE_RATE) ** (MIN_SCORED_FOR_ABSENCE - 1)
        assert one_fewer > 1 - EVIDENCE_CONFIDENCE, "threshold must be the SMALLEST that qualifies"

    def test_a_thin_negative_verdict_is_flagged_as_thin(self):
        """India's Environmental read Unaddressed on two sentences."""
        assert evidence_is_sufficient(n_scored=2, n_binding=0) is False

    def test_thin_means_the_document_barely_addresses_it_not_that_it_was_unread(self):
        """Every sentence of the supplied documents is swept, so two provisions
        is what the text contains. Saying the absence is "not publishable"
        beside a published verdict told the reader the tool distrusted itself."""
        from src.grading import verdict_confidence

        band, why = verdict_confidence(n_scored=2, n_binding=0, n_enforceable=0)

        assert band == "thin"
        assert "barely addresses" in why
        assert "publishable" not in why

    def test_a_thorough_negative_verdict_stands(self):
        """The EU's Environmental read Unaddressed on seventeen."""
        assert evidence_is_sufficient(n_scored=17, n_binding=0) is True

    def test_a_positive_finding_is_never_withheld(self):
        """Finding a duty is a finding, however little else was read."""
        assert evidence_is_sufficient(n_scored=1, n_binding=1) is True


class TestDuplicateProvisions:
    """Overlapping chunk windows delivered the same provision several times."""

    EGYPT = (
        "Ensure that transparency and Explainability requirements are jointly "
        "validated by Provider/Developer and Business Units (BU) during design."
    )

    def test_whitespace_variants_are_one_provision(self):
        from src.grading import dedupe_sentences

        variants = [
            self.EGYPT,
            self.EGYPT.replace("Provider/", "Provider /"),
            self.EGYPT.replace("  ", " ").replace(" during", "  during"),
        ]
        assert len(dedupe_sentences(variants)) == 1

    def test_genuinely_different_provisions_survive(self):
        from src.grading import dedupe_sentences

        pair = [self.EGYPT, "Providers shall publish a public registry of high-risk systems."]
        assert len(dedupe_sentences(pair)) == 2

    def test_order_is_preserved(self):
        from src.grading import dedupe_sentences

        assert dedupe_sentences(["b bbbb", "a aaaa", "b  bbbb"]) == ["b bbbb", "a aaaa"]


class TestSentenceFunctionGate:
    """Sentence function: non-operative text must not score as a duty."""

    def test_eu_recitals_are_not_operative(self):
        from src.grading import sentence_function

        # EU AI Act Recital 178 — the one that collapsed the EU run once before.
        s = (
            "Providers of high-risk AI systems are encouraged to start to comply, on a "
            "voluntary basis, with the relevant obligations of this Regulation."
        )
        assert sentence_function(s, is_recital=True) == "recital"
        assert sentence_function(s, is_recital=False) == "operative"

    def test_the_recital_boundary_is_found_by_article_one(self):
        from src.grading import recital_boundary

        chunks = [
            {"text": "(1) The purpose of this Regulation is...", "metadata": {"page_number": 5}},
            {
                "text": "Article 1\nSubject matter\n1. The purpose...",
                "metadata": {"page_number": 43},
            },
        ]
        assert recital_boundary(chunks) == 43

    def test_a_document_with_no_articles_is_left_alone(self):
        """A strategy or guideline must not be treated as having recitals."""
        from src.grading import recital_boundary

        assert (
            recital_boundary([{"text": "Pillar 1: build capacity", "metadata": {"page_number": 3}}])
            is None
        )

    def test_definitions_headings_descriptions_housekeeping(self):
        from src.grading import sentence_function

        cases = {
            "definition": "Diversity, non-discrimination and fairness means that AI systems "
            "are developed in a way that includes diverse actors.",
            "housekeeping": "In appointing members, the Cabinet Secretary shall ensure gender balance.",
            "descriptive": "Organizations are investing in vendor risk management and monitoring.",
            "heading": "(Restrictions on Provision of Personal Data to Third Parties)",
        }
        for expected, text in cases.items():
            assert sentence_function(text) == expected, text


class TestStructuralRelevance:
    """Structural relevance: duties the vocabulary gate has no word for."""

    # EU AI Act Article 17(1)(e), verbatim shape: a duty on a named party that
    # Transparency's vocabulary has no word for ("logging", not "audit trail").
    ART12 = (
        "A provider of a high-risk AI system shall ensure the logging capabilities "
        "record the period of each use of the system."
    )

    def test_a_duty_outside_the_vocabulary_is_admitted_on_structure(self):
        from src.deterministic import _sentence_has_core_term
        from src.grading import structurally_relevant

        assert not _sentence_has_core_term(self.ART12, "Transparency"), "premise: no core term"
        assert structurally_relevant(self.ART12, chunk_rank=2)

    def test_a_low_ranked_chunk_does_not_qualify(self):
        from src.grading import structurally_relevant

        assert not structurally_relevant(self.ART12, chunk_rank=99)

    def test_no_modal_no_admission(self):
        from src.grading import structurally_relevant

        assert not structurally_relevant("Providers often keep logs of system activity.", 1)

    def test_the_specificity_guard_drops_generic_provisions(self):
        """Kenya's 'programmes shall be conducted at national and county levels'
        qualified for six dimensions at once. It is specific to none."""
        from src.grading import apply_specificity_guard

        generic, specific = "the programmes shall be conducted", "providers shall log events"
        by_dim = {d: [generic] for d in "abcd"}
        by_dim["a"].append(specific)
        out = apply_specificity_guard(by_dim, max_dimensions=3)
        assert out["a"] == [specific]
        assert all(generic not in v for v in out.values())

    def test_a_provision_touching_few_dimensions_survives(self):
        from src.grading import apply_specificity_guard

        by_dim = {"a": ["providers shall log events"], "b": ["providers shall log events"]}
        out = apply_specificity_guard(by_dim, max_dimensions=3)
        assert out["a"] and out["b"]


class TestMechanismGate:
    """The mechanism gate: no dimension is governed while binding nothing."""

    def test_operational_requires_a_bound_mechanism(self):
        from src.grading import apply_mechanism_gate

        stage, note = apply_mechanism_gate("Operationalized", mechanisms_bound=0)
        assert stage == "Delegated" and note

    def test_top_stage_requires_two(self):
        from src.grading import apply_mechanism_gate

        assert apply_mechanism_gate("Institutionalized", 1)[0] == "Operationalized"
        assert apply_mechanism_gate("Institutionalized", 2)[0] == "Institutionalized"

    def test_the_gate_only_holds_verdicts_down(self):
        from src.grading import apply_mechanism_gate

        for stage in ("Unaddressed", "Emerging", "Delegated"):
            assert apply_mechanism_gate(stage, 9)[0] == stage


class TestListItemSeverance:
    """A KNOWN, UNFIXED defect. Pinned so the fix can be measured against it.

    Statutes enumerate: "...shall be subject to X concerning in particular:
    (a)... (f)... (g)...". The splitter severs each item from the stem that
    carries the subject and the modal, so the item scores T0 while the same
    duty written as one sentence scores T3. It under-scores exactly the
    instruments that are strongest, because statutes are list-heavy.
    """

    WHOLE = (
        "Providers of high-risk AI systems shall implement appropriate measures "
        "to detect, prevent and mitigate possible biases."
    )
    ITEM = (
        "(g) appropriate measures to detect, prevent and mitigate possible biases "
        "identified according to point (f);"
    )

    def test_the_same_duty_scores_differently_whole_and_severed(self):
        from src.evidence_strength import TIER_OBLIGATORY
        from src.grading import _classify_base

        assert _classify_base(self.WHOLE, dimension="Fairness").tier >= TIER_OBLIGATORY
        assert _classify_base(self.ITEM, dimension="Fairness").tier == 0, (
            "if this now passes, list-item severance has been fixed — "
            "update EU Fairness's expected mechanism count"
        )


class TestListItemRepair:
    """List items: statutes enumerate, and each item keeps its stem's duty."""

    STEM = (
        "Training, validation and testing data sets shall be subject to data "
        "governance practices concerning in particular:"
    )
    ITEM_F = "(f) examination in view of possible biases likely to affect health and safety"
    ITEM_G = "(g) appropriate measures to detect, prevent and mitigate possible biases"

    def test_items_inherit_the_stem(self):
        from src.grading import rejoin_list_items

        out = rejoin_list_items([self.STEM, self.ITEM_F, self.ITEM_G])
        assert out[0] == self.STEM, "the stem is a provision in its own right"
        assert out[1].startswith(self.STEM) and self.ITEM_F in out[1]
        assert out[2].startswith(self.STEM) and self.ITEM_G in out[2]

    def test_a_rejoined_item_is_scored_as_the_duty_it_is(self):
        from src.evidence_strength import TIER_OBLIGATORY
        from src.grading import classify_provision, rejoin_list_items

        rejoined = rejoin_list_items([self.STEM, self.ITEM_G])[-1]
        assert classify_provision(rejoined, dimension="Fairness").tier >= TIER_OBLIGATORY
        assert classify_provision(self.ITEM_G, dimension="Fairness").tier == 0

    def test_a_list_cannot_reach_across_into_the_next_provision(self):
        from src.grading import rejoin_list_items

        out = rejoin_list_items(
            [
                self.STEM,
                self.ITEM_F,
                "This Regulation shall apply from 2 August 2026.",
                "(a) an item belonging to something else",
            ]
        )
        assert not out[-1].startswith(self.STEM)

    def test_an_item_with_no_stem_is_left_alone(self):
        from src.grading import rejoin_list_items

        assert rejoin_list_items(["(a) a lone item"]) == ["(a) a lone item"]


class TestArtifactBorneDuties:
    """Artifact-borne duties: product-safety drafting regulates the thing."""

    def test_a_duty_on_the_artifact_binds(self):
        from src.evidence_strength import TIER_OBLIGATORY
        from src.grading import _classify_base, classify_provision

        for s in (
            "High-risk AI systems shall be accompanied by instructions for use.",
            "Training data sets shall be subject to data governance practices.",
            "An AI system shall be designed to enable human oversight.",
        ):
            assert _classify_base(s).tier == 0, "v2 misses it"
            assert classify_provision(s).tier >= TIER_OBLIGATORY, s

    def test_government_self_direction_is_still_capped(self):
        from src.evidence_strength import TIER_ASSIGNED
        from src.grading import classify_provision

        s = "The Authority shall ensure the AI system register is maintained."
        assert classify_provision(s).tier == TIER_ASSIGNED

    def test_aspiration_about_an_artifact_is_still_aspiration(self):
        from src.grading import classify_provision

        assert classify_provision("AI systems should be transparent.").tier == 0

    def test_an_artifact_duty_is_not_enforceable_without_a_consequence(self):
        from src.evidence_strength import TIER_ENFORCEABLE, TIER_OBLIGATORY
        from src.grading import classify_provision

        plain = classify_provision("High-risk AI systems shall be accompanied by logs.")
        assert plain.tier == TIER_OBLIGATORY
        withpen = classify_provision(
            "High-risk AI systems shall be accompanied by logs, and a fine applies on breach."
        )
        assert withpen.tier == TIER_ENFORCEABLE


class TestMechanismGateCascades:
    """A statute with no bound mechanism: demotions must chain, not stop at the first."""

    def test_top_stage_with_no_bound_mechanism_falls_all_the_way(self):
        from src.grading import apply_mechanism_gate

        stage, note = apply_mechanism_gate("Institutionalized", mechanisms_bound=0)
        assert stage == "Delegated", "must not stop at Operationalized"
        assert note

    def test_one_bound_mechanism_stops_at_operationalized(self):
        from src.grading import apply_mechanism_gate

        assert apply_mechanism_gate("Institutionalized", 1)[0] == "Operationalized"


class TestConsultationDocuments:
    """Found on the UK white paper — a genre the first five jurisdictions
    did not contain. A consultation asks what the law SHOULD be, in the
    vocabulary of obligation, while imposing nothing."""

    def test_a_consultation_question_is_not_a_duty(self):
        from src.grading import sentence_function

        for q in (
            "Are there other measures we could require of organisations "
            "to improve transparency for AI?",
            "2: Are there other measures we could require of organisations?",
        ):
            assert sentence_function(q) == "consultative", q

    def test_an_erratum_is_not_a_duty(self):
        from src.grading import sentence_function

        s = (
            "Text should read: 1: Do you agree that requiring organisations to make "
            "it clear when they are using AI would improve transparency?"
        )
        assert sentence_function(s) == "consultative"

    def test_deliberation_by_the_author_is_not_a_duty(self):
        from src.grading import sentence_function

        s = (
            "We recognise the need to consider which actors should be responsible "
            "and liable for complying with the principles."
        )
        assert sentence_function(s) == "consultative"


class TestAgentlessEnforcement:
    """Found on China. Civil-law drafting states the consequence and leaves
    the actor implicit — the consequence is the grammatical subject."""

    def test_passive_consequence_is_enforcement(self):
        from src.evidence_strength import TIER_ENFORCEABLE
        from src.grading import classify_provision

        for s in (
            "Where a crime is constituted, criminal liability shall be pursued "
            "in accordance with the law.",
            "Public security administrative sanctions shall be imposed in accordance with the law.",
        ):
            assert classify_provision(s).tier == TIER_ENFORCEABLE, s

    def test_punish_is_in_the_consequence_lexicon(self):
        """Standard in civil-law translation, absent from Anglo drafting."""
        from src.evidence_strength import TIER_ENFORCEABLE
        from src.grading import CONSEQUENCE_RE, classify_provision

        assert CONSEQUENCE_RE.search("shall be punished according to law")
        s = "Providers who violate these provisions shall be punished under relevant laws."
        assert classify_provision(s).tier == TIER_ENFORCEABLE

    def test_a_passive_with_no_consequence_is_not_enforcement(self):
        from src.grading import is_agentless_enforcement

        assert not is_agentless_enforcement("Guidance shall be published in due course.")
        assert not is_agentless_enforcement("The register shall be maintained.")

    def test_aspiration_and_self_direction_are_untouched(self):
        from src.evidence_strength import TIER_ASSIGNED
        from src.grading import classify_provision

        assert classify_provision("AI should be developed responsibly.").tier == 0
        assert (
            classify_provision("The Ministry shall develop guidelines for the sector.").tier
            == TIER_ASSIGNED
        )

    def test_a_voluntary_instrument_still_caps_it(self):
        from src.evidence_strength import TIER_INTENTIONAL
        from src.grading import classify_provision

        s = "Criminal liability shall be pursued in accordance with the law."
        assert classify_provision(s, document_is_nonbinding=True).tier == TIER_INTENTIONAL


class TestBeToObligation:
    """'be + to-infinitive' is a standard English deontic construction
    (Quirk et al.), added on grammatical grounds."""

    ART21 = (
        "Article 21: Where providers violate these Measures, penalties are to be "
        "given by the relevant regulatory departments in accordance with the law."
    )

    def test_a_penalty_article_written_with_be_to_is_enforceable(self):
        from src.evidence_strength import TIER_ENFORCEABLE
        from src.grading import classify_provision

        assert classify_provision(self.ART21).tier == TIER_ENFORCEABLE

    def test_it_reaches_the_artifact_branch_too(self):
        """Normalisation runs BEFORE the ladder, so every branch benefits."""
        from src.evidence_strength import TIER_OBLIGATORY
        from src.grading import classify_provision

        s = "AI systems are to be developed in accordance with these provisions."
        assert classify_provision(s).tier >= TIER_OBLIGATORY

    def test_the_future_arrangement_reading_is_not_an_obligation(self):
        """'is to' also means 'is scheduled to'. Requiring a passive participle
        AND a duty-bearer keeps the two apart."""
        from src.grading import classify_provision

        assert classify_provision("The report is to be published next year.").tier == 0

    def test_evidence_quotes_the_document_not_the_normalisation(self):
        from src.grading import classify_provision

        assert "are to be" in classify_provision(self.ART21).text
        assert "shall be given" not in classify_provision(self.ART21).text

    def test_existing_constructions_are_unchanged(self):
        from src.evidence_strength import TIER_ASSIGNED, TIER_OBLIGATORY
        from src.grading import classify_provision

        assert (
            classify_provision(
                "Providers of high-risk AI systems shall maintain an audit trail."
            ).tier
            == TIER_OBLIGATORY
        )
        assert classify_provision("The Ministry shall develop guidelines.").tier == TIER_ASSIGNED
        assert classify_provision("AI should be transparent.").tier == 0


class TestImpositionLexiconSenses:
    """The imposition stems were audited against what they actually match."""

    def test_require_meaning_need_is_not_a_duty(self):
        """Kenya's entire Inclusivity verdict rested on this one sentence."""
        from src.grading import classify_provision

        s = (
            "Non-tech professionals including policymakers, educators, and business "
            "leaders require AI fluency for ethical and inclusive deployment."
        )
        assert classify_provision(s).tier == 0

    def test_every_deontic_form_of_require_still_binds(self):
        from src.evidence_strength import TIER_OBLIGATORY
        from src.grading import classify_provision

        for s in (
            "Providers of high-risk AI systems are required to maintain an audit trail.",
            "The regulation requires that providers publish a registry.",
            "Providers shall comply with the requirements of this Article.",
        ):
            assert classify_provision(s).tier >= TIER_OBLIGATORY, s

    def test_barriers_is_not_a_prohibition(self):
        """`bar*` matched barriers(26), baringo(2 — a Kenyan county), barometer(1)."""
        from src.grading import classify_provision

        assert (
            classify_provision(
                "Addressing barriers to adoption remains a priority for the sector."
            ).tier
            == 0
        )

    def test_compelling_is_not_compulsion(self):
        """`compel*` matched exactly one token in the corpus: 'compelling'."""
        from src.evidence_strength import IMPOSITION_RE

        assert not IMPOSITION_RE.search("There is a compelling case for adoption")
        assert IMPOSITION_RE.search("Providers may be compelled to disclose")

    def test_restrictive_is_an_adjective(self):
        from src.evidence_strength import IMPOSITION_RE

        assert not IMPOSITION_RE.search("a restrictive interpretation of the clause")
        assert IMPOSITION_RE.search("the Act restricts automated profiling")


class TestOversightNeedsSubjection:
    """Oversight is force only when the regulated party is its object."""

    def test_mention_of_monitoring_is_not_a_duty(self):
        """Carried 8% of the corpus's binding evidence on nothing."""
        from src.grading import classify_provision

        assert (
            classify_provision(
                "Organizations are investing in vendor risk management and continuous monitoring."
            ).tier
            == 0
        )

    def test_being_subject_to_supervision_binds(self):
        from src.evidence_strength import TIER_OBLIGATORY
        from src.grading import classify_provision

        for s in (
            "Providers are subject to supervision by the competent authority.",
            "Deployers operate under the supervision of the national authority.",
            "Operators shall be subject to periodic inspection.",
        ):
            assert classify_provision(s).tier >= TIER_OBLIGATORY, s

    def test_self_assessment_still_does_not_bind(self):
        """Egypt calls its own audit instrument a 'Self Assessment checklist'."""
        from src.grading import classify_provision

        assert (
            classify_provision(
                "Organizations should complete the comprehensive self assessment "
                "checklist covering audit and monitoring practices."
            ).tier
            < 3
        )


class TestAdministrativeSanctions:
    """PIPL imposes every one of its remedies in words the lexicon lacked."""

    def test_order_corrections_and_warnings_are_enforcement(self):
        from src.evidence_strength import TIER_ENFORCEABLE
        from src.grading import classify_provision

        s = (
            "Departments performing personal information protection duties are to "
            "order corrections, confiscate unlawful gains, and give warnings."
        )
        assert classify_provision(s).tier == TIER_ENFORCEABLE

    def test_in_order_to_is_still_not_a_power(self):
        """A bare 'order' stays excluded — 'in order to' is everywhere."""
        from src.grading import classify_provision

        assert (
            classify_provision(
                "The Commission shall establish a working group in order to "
                "coordinate research across member states."
            ).tier
            < 3
        )

    def test_early_warning_system_is_not_a_sanction(self):
        from src.grading import ADMIN_SANCTION_RE

        assert not ADMIN_SANCTION_RE.search("an early warning system for outages")
        assert ADMIN_SANCTION_RE.search("the regulator issued a warning to the provider")


class TestSourceScopedForce:
    """A pool mixes documents, so the ceiling has to be asked per sentence."""

    def test_unenforced_document_cannot_oblige_but_can_delegate(self):
        from src.evidence_strength import TIER_ASSIGNED
        from src.grading import classify_provision

        duty = "Providers must publish a model card for each deployed system."
        assert classify_provision(duty).tier > TIER_ASSIGNED
        assert classify_provision(duty, document_is_unenforced=True).tier == TIER_ASSIGNED

    def test_voluntary_beats_unenforced(self):
        """A self-declared voluntary document caps lower than a toothless one."""
        from src.evidence_strength import TIER_INTENTIONAL
        from src.grading import classify_provision

        duty = "Providers must publish a model card for each deployed system."
        assert (
            classify_provision(duty, document_is_nonbinding=True, document_is_unenforced=True).tier
            == TIER_INTENTIONAL
        )

    def test_profile_caps_each_sentence_by_its_own_source(self):
        from src.grading import SOURCE_UNENFORCED

        statute = "A data controller shall notify the Commissioner of any breach."
        guidance = "Departments must record each automated decision in the register."
        profile = build_provision_profile(
            [statute, guidance],
            source_force={statute: "", guidance: SOURCE_UNENFORCED},
        )
        assert profile.n_binding == 1

    def test_unknown_sentence_is_not_capped(self):
        """rejoin_list_items can produce a string that is nobody's key."""
        from src.grading import SOURCE_UNENFORCED

        known = "A data controller shall notify the Commissioner of any breach."
        profile = build_provision_profile(
            ["Operators shall maintain a register of deployed systems."],
            source_force={known: SOURCE_UNENFORCED},
        )
        assert profile.n_binding == 1


class TestVoluntarinessIsDetectedAsWritten:
    def test_soft_law_preface_is_a_disclaimer(self):
        """Japan's AI Guidelines for Business, verbatim."""
        from src.evidence_strength import detect_nonbinding_document

        assert detect_nonbinding_document(
            [
                "Thus, it was decided to draw up guidelines on the basis of the "
                "goal-based concept that would lead to the achievement of purposes "
                "through soft laws without any legally binding force."
            ]
        )

    def test_diagnosis_of_the_status_quo_is_not_a_disclaimer(self):
        """India's guidelines say this ABOUT other frameworks, not themselves."""
        from src.evidence_strength import detect_nonbinding_document

        assert not detect_nonbinding_document(
            [
                "Current voluntary frameworks lack legal enforceability, and there "
                "is insufficient clarity on how liability should be attributed."
            ]
        )

    def test_early_compliance_recital_is_still_not_a_disclaimer(self):
        """EU AI Act Recital 178 — the false positive that capped the Act."""
        from src.evidence_strength import detect_nonbinding_document

        assert not detect_nonbinding_document(
            [
                "Providers are encouraged to start to comply, on a voluntary basis, "
                "with the relevant obligations of this Regulation already during "
                "the transitional period."
            ]
        )


class TestAccessibilitySenses:
    """Bare "accessib" stays out; the disability compounds come in."""

    def test_accessibility_requirements_is_inclusivity(self):
        """The AI Act's only binding inclusivity duty names the directives."""
        from src.deterministic import _sentence_has_core_term

        assert _sentence_has_core_term(
            "Providers shall ensure full compliance with accessibility "
            "requirements, including Directive (EU) 2016/2102.",
            "Inclusivity",
        )

    def test_merely_accessible_information_is_not(self):
        from src.deterministic import _sentence_has_core_term

        for s in (
            "Providers shall supply relevant, accessible and comprehensible "
            "information to deployers.",
            "The information shall be accessible only to market surveillance "
            "authorities and the Commission.",
            "A space is publicly accessible if access is subject to conditions.",
        ):
            assert not _sentence_has_core_term(s, "Inclusivity"), s


class TestDutyBearersTheCorpusUses:
    """Actors the instruments regulate that the lexicon did not name."""

    def test_pipl_addressee_is_a_regulated_party(self):
        """27 PIPL duties scored as no duty at all without this."""
        from src.evidence_strength import TIER_OBLIGATORY
        from src.grading import classify_provision

        scored = classify_provision(
            "Personal information handlers shall take necessary measures to "
            "ensure the security of personal information."
        )
        assert scored.tier >= TIER_OBLIGATORY
        assert scored.duty_bearer == "regulated"

    def test_notified_bodies_bear_duties(self):
        from src.evidence_strength import TIER_OBLIGATORY
        from src.grading import classify_provision

        assert (
            classify_provision(
                "Notified bodies shall participate in coordination activities as "
                "referred to in Article 38."
            ).tier
            >= TIER_OBLIGATORY
        )

    def test_a_commissioner_is_a_government_body(self):
        from src.grading import classify_provision

        scored = classify_provision(
            "The Commissioner shall investigate complaints and may impose a "
            "penalty notice under this Part."
        )
        assert scored.duty_bearer == "government"
        assert scored.has_enforcement


class TestVocabularyOutsideTheGdprTradition:
    """Every tradition writes these duties; only one writes them in our words."""

    def test_consumer_law_phrasing_is_a_non_discrimination_duty(self):
        """China states it as a right to fair transactions, and binds it."""
        from src.grading import classify_provision
        from src.mechanism_matching import detect_mechanisms

        s = (
            "Article 21: Where the providers of algorithmic recommendation services "
            "market goods or provide services to consumers, they shall protect the "
            "consumers' rights to fair transactions."
        )
        found = detect_mechanisms([classify_provision(s, dimension="Fairness")], "Fairness")
        assert "non-discrimination duty" in found.present

    def test_minors_and_seniors_are_protected_groups(self):
        from src.grading import classify_provision
        from src.mechanism_matching import detect_mechanisms

        s = (
            "Article 19: When the providers of algorithmic recommendation services "
            "provide seniors with services, they shall safeguard the rights and "
            "interests lawfully enjoyed by the seniors."
        )
        found = detect_mechanisms([classify_provision(s, dimension="Fairness")], "Fairness")
        assert "protected characteristics" in found.present


class TestEcologicalIsNotEnvironmental:
    """生态 renders as "ecological" and means the CONTENT ecosystem."""

    def test_content_ecosystem_management_is_not_an_environmental_duty(self):
        from src.deterministic import _sentence_has_core_term

        assert not _sentence_has_core_term(
            "Providers shall strengthen the ecological management of algorithm "
            "recommendation service pages.",
            "Environmental Sustainability",
        )

    def test_the_genuine_senses_still_match(self):
        from src.deterministic import _sentence_has_core_term

        for s in (
            "Providers shall report the ecological footprint of training runs.",
            "The assessment shall cover the ecological impact of the system.",
            "Deployers shall disclose energy consumption and carbon emissions.",
        ):
            assert _sentence_has_core_term(s, "Environmental Sustainability"), s


class TestFrameworkSalience:
    """Ordering the gaps, never changing the verdict."""

    def test_absent_mechanisms_rank_by_how_many_instruments_expect_them(self, monkeypatch):
        from src import framework_salience as fs

        monkeypatch.setattr(
            fs,
            "mechanism_salience",
            lambda: {
                "Safety|pre-deployment testing": 36,
                "Safety|risk assessment": 29,
                "Safety|human failsafe / shutdown": 5,  # below the consensus floor
            },
        )
        ranked = fs.rank_absent(
            "Safety", ["human failsafe / shutdown", "pre-deployment testing", "risk assessment"]
        )

        assert [r["mechanism"] for r in ranked] == ["pre-deployment testing", "risk assessment"]

    def test_an_unreachable_corpus_shows_nothing_rather_than_guessing(self, monkeypatch):
        """Salience is presentation, so losing it must not fail an analysis — and
        must not invent a priority order it cannot justify either."""
        from src import framework_salience as fs

        monkeypatch.setattr(fs, "mechanism_salience", lambda: {})

        assert fs.rank_absent("Safety", ["risk assessment", "pre-deployment testing"]) == []

    @staticmethod
    def _salience_over(monkeypatch, rows):
        """mechanism_salience over a fake collection holding `rows`."""
        from src import framework_salience as fs
        from src import vectorstore

        class _Collection:
            def get(self, where, include, limit, offset):
                hits = [r for r in rows if r[1]["workspace_id"] == where["workspace_id"]]
                page = hits[offset : offset + limit]
                return {"documents": [t for t, _ in page], "metadatas": [m for _, m in page]}

        monkeypatch.setattr(vectorstore, "open_collection", lambda *a, **k: _Collection())
        fs.mechanism_salience.cache_clear()
        try:
            return fs.mechanism_salience()
        finally:
            fs.mechanism_salience.cache_clear()

    @staticmethod
    def _a_mechanism():
        from src.evidence_strength import DIMENSION_MECHANISMS

        dimension, table = next(iter(DIMENSION_MECHANISMS.items()))
        mechanism, cues = next(iter(table.items()))
        return f"{dimension}|{mechanism}", f"The instrument sets out {cues[0]} in full."

    def test_a_country_document_is_never_counted_as_a_reference(self, monkeypatch):
        """The corpus side of the count must exclude what is being assessed."""
        key, text = self._a_mechanism()
        rows = [
            (text, {"workspace_id": "", "framework": "Library A"}),
            (text + " Again.", {"workspace_id": "", "framework": "Library A"}),
            (text, {"workspace_id": "ws-1", "document_name": "Country Act.pdf"}),
            (text + " Again.", {"workspace_id": "ws-1", "document_name": "Country Act.pdf"}),
        ]

        assert self._salience_over(monkeypatch, rows)[key] == 1

    def test_a_framework_indexed_once_per_role_is_not_counted_twice(self, monkeypatch):
        # A two-role framework is stored as two copies of every chunk, so one
        # passing mention used to clear the two-chunk bar on its own.
        key, text = self._a_mechanism()
        rows = [
            (text, {"workspace_id": "", "framework": "Two Roles", "roles": "module_1_normative"}),
            (text, {"workspace_id": "", "framework": "Two Roles", "roles": "module_2_practical"}),
        ]

        assert self._salience_over(monkeypatch, rows)[key] == 0


class TestPriorityFloor:
    """A minority expectation is not a priority."""

    def test_sub_consensus_gaps_are_dropped_not_ranked_last(self, monkeypatch):
        """ "purpose limitation, expected by 1 of 43" made the panel look arbitrary."""
        from src import framework_salience as fs

        monkeypatch.setattr(
            fs,
            "mechanism_salience",
            lambda: {
                "Privacy|purpose limitation": 1,
                "Privacy|consent": 30,
            },
        )
        ranked = fs.rank_absent("Privacy", ["purpose limitation", "consent"])

        assert [r["mechanism"] for r in ranked] == ["consent"]

    def test_the_denominator_is_counted_not_inferred(self):
        """It returned the largest salience value, printing "31 of 39" over 43."""
        import inspect

        from src import framework_salience as fs

        src = inspect.getsource(fs.framework_count)
        assert "max(" not in src


class TestSubjectionIsNotControl:
    """ "Under the control of X" says what X controls, not what X answers to."""

    def test_control_and_authority_are_not_subjection(self):
        from src.grading import SUBJECTION_RE

        for s in (
            "logs to the extent they are under the control of the provider",
            "a data processing environment under the control of the prospective provider",
        ):
            assert not SUBJECTION_RE.search(s), s

    def test_real_subjection_still_matches(self):
        from src.grading import SUBJECTION_RE

        for s in (
            "deployers operating under the supervision of the authority",
            "systems placed under the oversight of the Commission",
            "premises under the inspection of the notified body",
        ):
            assert SUBJECTION_RE.search(s), s


class TestDimensionAwareStructuralAdmission:
    """Structural admission trusts rank, so it needs a topic veto."""

    def test_a_provision_naming_another_dimension_is_not_admitted_here(self):
        """Six DPDP privacy duties were India's Safety evidence on this path."""
        from src.deterministic import _sentence_has_core_term

        s = (
            "(6) In the event of a personal data breach, the Data Fiduciary shall "
            "give the Board intimation of such breach."
        )
        assert _sentence_has_core_term(s, "Privacy")
        assert not _sentence_has_core_term(s, "Safety")

    def test_the_veto_is_wired_into_structural_admission(self):
        import inspect

        from src.gap_analyzer import GapAnalyzer

        src = inspect.getsource(GapAnalyzer._structural_candidates)
        assert "_sentence_has_core_term(sent, other)" in src


class TestBreadthFloorNeedsEvidence:
    """The breadth floor fired hardest where the evidence was weakest.

    Measured across the corpus it demoted 12 of 55 cells, four of them China
    at 0 of 5 or 0 of 6 — a jurisdiction carrying six binding provisions in
    both Safety and Human Autonomy, held at Partial because mechanism matching
    returned nothing. The cue selector was measured at 20% precision, so a
    zero count cannot tell "no mechanisms exist" apart from "none were found".
    """

    def _profile_and_mechs(self, met, total):
        from src.grading import build_provision_profile
        from src.mechanism_matching import MechanismMatch

        binding = [
            "A data fiduciary shall implement appropriate technical and organisational measures.",
            "The controller must notify the supervisory authority of a personal data breach.",
            "Providers shall ensure high-risk systems comply before placing them on the market.",
        ]
        profile = build_provision_profile(binding, dimension="Privacy")
        names = [f"mech{i}" for i in range(met)]
        absent = [f"absent{i}" for i in range(total - met)]
        return profile, MechanismMatch(
            dimension="Privacy", present=dict.fromkeys(names, 3), absent=absent
        )

    def test_zero_detections_do_not_demote(self):
        from src.evidence_strength import coverage_from_profile

        profile, mechs = self._profile_and_mechs(met=0, total=6)
        label, _ = coverage_from_profile(profile, mechanisms=mechs)

        assert label == "Covered", "an absence nothing measured must not hold a verdict down"

    def test_a_measured_shortfall_still_demotes(self):
        """The guard must not disable the floor — one of six is a real, counted
        shortfall and still reads Partial."""
        from src.evidence_strength import coverage_from_profile

        profile, mechs = self._profile_and_mechs(met=1, total=6)
        label, _ = coverage_from_profile(profile, mechanisms=mechs)

        assert label == "Partial"


class TestExcludedSentencesAreNotScored:
    """A passage about another jurisdiction's law is not this document's provision."""

    def test_a_third_party_description_is_excluded_from_the_counts(self):
        from src.grading import build_provision_profile

        profile = build_provision_profile(
            [
                "In Singapore, the Model AI Governance Framework encourages organisations "
                "to disclose AI use.",
                "Every provider shall register the system with the Commission.",
            ],
            dimension="Transparency",
            own_jurisdiction="Kenya",
        )

        assert profile.n_scored == 1
        assert profile.n_excluded_foreign == 1


class TestEnforcementBackingUsesTheScoringClassifier:
    def test_an_artifact_borne_duty_earns_backing(self):
        # "The AI system shall..." binds through the artifact. The base ladder
        # the backing check used could not see it, while the profile could.
        from src.grading import TIER_OBLIGATORY, classify_provision, dimension_enforcement_backing

        duty = "High-risk AI systems shall be designed to allow effective human oversight."
        assert classify_provision(duty).tier >= TIER_OBLIGATORY

        assert dimension_enforcement_backing({"Act.pdf": [duty]}, {"Act.pdf"}) is True
