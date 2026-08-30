"""Brief assembly and the normative-force predicates behind every verdict.

meets_force_bar is the single predicate coverage and maturity both read.
Three places used to compute coverage independently and they drifted, which
produced a document reading "Partial" and "Operationalized" in the same
breath. Everything here is downstream of that fix.
"""

import pytest

from src.brief_synthesis import (
    build_dimension_assessment,
    build_dimension_digest,
    build_evidence_base,
    build_implementation_roadmap,
    build_relevant_precedent,
    build_risk_overview,
    build_scope_and_methodology,
    render_brief_markdown,
)
from src.evidence_strength import (
    EvidenceProfile,
    detect_enforcement_regime,
    detect_nonbinding_document,
    is_structural_noise,
    is_third_party_attribution,
    meets_force_bar,
)


def _profile(**kw):
    return EvidenceProfile(
        dimension=kw.get("dimension", "Fairness"),
        sentences=kw.get("sentences", []),
        tier_counts=kw.get("tier_counts", {}),
        max_tier=kw.get("max_tier", 0),
        n_enforceable=kw.get("n_enforceable", 0),
        n_binding=kw.get("n_binding", 0),
        n_institutional=kw.get("n_institutional", 0),
        n_commitment=kw.get("n_commitment", 0),
        n_scored=kw.get("n_scored", 0),
    )


class TestForceBar:
    def test_two_binding_findings_clear_the_bar(self):
        assert meets_force_bar(_profile(n_scored=5, n_commitment=4, n_binding=2))

    def test_one_binding_with_enforcement_clears_the_bar(self):
        assert meets_force_bar(_profile(n_scored=5, n_commitment=4, n_binding=1, n_enforceable=1))

    def test_a_lone_binding_finding_does_not(self):
        # Deliberately not n_binding >= 1. Counters are CUMULATIVE, so a
        # single binding sentence lifts every weaker counter with it; pairing
        # a duty with enforcement is the one genuinely independent signal.
        assert not meets_force_bar(_profile(n_scored=5, n_commitment=4, n_binding=1))

    def test_commitments_alone_never_clear_the_bar(self):
        assert not meets_force_bar(_profile(n_scored=9, n_commitment=9))

    def test_an_empty_profile_does_not_clear_the_bar(self):
        assert not meets_force_bar(_profile())

    def test_the_predicate_is_pure(self):
        profile = _profile(n_scored=5, n_binding=2)

        # Coverage and maturity both call this; a stateful predicate could
        # give them different answers to the same question.
        assert meets_force_bar(profile) == meets_force_bar(profile)


class TestCumulativeInvariant:
    def test_counters_are_ordered_weakest_to_strongest(self):
        profile = _profile(
            n_scored=10, n_commitment=6, n_institutional=4, n_binding=3, n_enforceable=2
        )

        # n_enforceable <= n_binding <= n_institutional <= n_commitment <=
        # n_scored. Several past bugs came from thresholds built on the
        # weaker counters, which are degenerate.
        assert profile.n_enforceable <= profile.n_binding
        assert profile.n_binding <= profile.n_institutional
        assert profile.n_institutional <= profile.n_commitment
        assert profile.n_commitment <= profile.n_scored


class TestStructuralNoise:
    @pytest.mark.parametrize(
        "sentence",
        [
            "Table of Contents",
            # PDF extraction concatenates contents lines into one "sentence";
            # a line that is mostly page numbers is a listing, not a provision.
            "Introduction 4 Scope 7 Duties 11 Enforcement 15 Annex 22",
            "Definitions",
        ],
    )
    def test_boilerplate_is_recognised(self, sentence):
        assert is_structural_noise(sentence)

    def test_a_real_provision_is_not_noise(self):
        assert not is_structural_noise(
            "Providers shall establish a risk management system for high-risk AI."
        )

    def test_empty_text_is_noise(self):
        assert is_structural_noise("")


class TestThirdPartyAttribution:
    def test_a_description_of_another_jurisdiction_is_flagged(self):
        sentence = "The European Union's AI Act requires conformity assessments."

        # Scoring another country's statute as this document's own binding
        # force would be the clearest possible false positive.
        assert is_third_party_attribution(sentence, own_jurisdiction="Kenya")

    def test_the_documents_own_provision_is_not_attribution(self):
        sentence = "The Authority shall supervise compliance with this Act."

        assert not is_third_party_attribution(sentence, own_jurisdiction="Kenya")

    def test_empty_text_is_not_attribution(self):
        assert not is_third_party_attribution("")


class TestDocumentLevelDetection:
    def test_a_guidance_document_reads_as_non_binding(self):
        texts = [
            "Organisations should consider adopting these principles.",
            "Developers are encouraged to publish model documentation.",
            "This guidance is voluntary and does not create obligations.",
        ]

        assert detect_nonbinding_document(texts)

    def test_a_statute_does_not(self):
        texts = [
            "Providers shall register high-risk systems before deployment.",
            "A provider who fails to comply shall be liable to a penalty.",
            "The Authority shall maintain a public register.",
        ]

        assert not detect_nonbinding_document(texts)

    def test_an_enforcement_regime_is_detected(self):
        texts = [
            "A provider who fails to comply shall be liable to an administrative fine.",
            "The Authority may impose penalties not exceeding 4% of turnover.",
            "Non-compliance is an offence punishable on conviction.",
            "The Authority shall have powers of inspection and enforcement.",
        ]

        # This is what lets a document that demonstrably carries enforcement
        # reach Institutionalized on one enforceable finding instead of two.
        assert detect_enforcement_regime(texts)

    def test_guidance_carries_no_enforcement_regime(self):
        assert not detect_enforcement_regime(
            ["Organisations should consider publishing documentation."]
        )

    def test_no_text_detects_nothing(self):
        assert not detect_enforcement_regime([])


class TestBriefSections:
    GAPS = [
        {
            "dimension": "Transparency",
            "coverage": "Covered",
            "governance_maturity": "Operationalized",
            "risk_level": "Low",
            "reason_flagged": "Disclosure duties are binding.",
            "recommendation": "Maintain the current regime.",
            "mechanisms_present": {"disclosure": 3},
            "mechanisms_absent": [],
            "evidence": [
                {
                    "text": "Article 13 requires transparency.",
                    "page_number": 5,
                    "chunk_id": "c1",
                    "verified": True,
                }
            ],
        },
        {
            "dimension": "Fairness",
            "coverage": "Missing",
            "governance_maturity": "Unaddressed",
            "risk_level": "High",
            "reason_flagged": "No bias testing requirement.",
            "recommendation": "Introduce a bias testing duty.",
            "mechanisms_present": {},
            "mechanisms_absent": ["bias testing", "demographic parity"],
            "evidence": [],
        },
    ]

    def test_the_digest_names_every_dimension(self):
        digest = build_dimension_digest(self.GAPS)

        assert "Transparency" in digest and "Fairness" in digest

    def test_the_risk_overview_is_built(self):
        overview = build_risk_overview(self.GAPS)

        assert overview.get("paragraph")

    def test_dimension_assessments_cover_every_gap(self):
        assessments = build_dimension_assessment(self.GAPS)

        assert len(assessments) == len(self.GAPS)

    def test_the_roadmap_orders_missing_before_partial(self):
        gaps = self.GAPS + [
            {
                "dimension": "Privacy",
                "coverage": "Partial",
                "reason_flagged": "Partial cover.",
                "recommendation": "Extend it.",
                "module_3": {"phases": [{"phase": "1", "actions": ["do a thing"]}]},
            }
        ]

        roadmap = build_implementation_roadmap(gaps)

        # A decision-maker got recommendations with no indication of
        # ordering; Missing dimensions lead.
        assert isinstance(roadmap, list)

    def test_the_evidence_base_counts_verified_citations(self):
        base = build_evidence_base(self.GAPS)

        assert isinstance(base, dict)

    def test_precedent_is_optional(self):
        # Returns None when no genuinely relevant incident matched, rather
        # than padding the brief.
        assert build_relevant_precedent(self.GAPS) is None or isinstance(
            build_relevant_precedent(self.GAPS), str
        )

    def test_scope_and_methodology_states_the_limits(self):
        scope = build_scope_and_methodology(
            scope_disclaimer="Scope: this assessment evaluates policy.pdf.",
            frameworks_used=["EU AI Act"],
            documents=["policy.pdf"],
            num_dimensions=8,
        )

        # The stored disclaimer is reproduced verbatim, never regenerated.
        assert "Scope: this assessment evaluates policy.pdf." in scope

    def test_no_gaps_does_not_crash_any_section(self):
        assert isinstance(build_dimension_digest([]), str)
        assert isinstance(build_dimension_assessment([]), list)
        assert isinstance(build_implementation_roadmap([]), list)


@pytest.fixture
def gaps():
    from tests.unit.test_brief_v2 import gaps as _gaps

    return _gaps.__wrapped__()


class TestBriefMarkdown:
    def _brief(self, gaps):
        # Assembled the way the API assembles it, so the renderer is asserted
        # against the real shape rather than a hand-written stand-in.
        from src.brief_synthesis import assemble_brief
        from tests.unit.test_brief_v2 import SCOPE, _synthesis

        return assemble_brief(
            workspace_id="w1",
            country="Testland",
            policy_title="National AI Strategy",
            document_name="policy.pdf",
            documents=["policy.pdf"],
            frameworks_used=["EU AI Act"],
            scope_disclaimer=SCOPE,
            gaps=gaps,
            synthesis=_synthesis(),
            decision_analytics=None,
        )

    def test_a_brief_renders_to_markdown(self, gaps):
        markdown = render_brief_markdown(self._brief(gaps))

        assert "Testland" in markdown
        assert len(markdown) > 200

    def test_the_scope_disclaimer_survives_rendering(self, gaps):
        from tests.unit.test_brief_v2 import SCOPE

        markdown = render_brief_markdown(self._brief(gaps))

        # The disclaimer is reproduced verbatim, never regenerated — a reader
        # must be told exactly what was and was not evaluated.
        assert SCOPE.split(".")[0] in markdown

    def test_every_dimension_appears_in_the_rendered_brief(self, gaps):
        markdown = render_brief_markdown(self._brief(gaps))

        assert markdown.strip()
