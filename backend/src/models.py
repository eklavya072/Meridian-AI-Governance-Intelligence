from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class RiskLevel(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INSUFFICIENT_EVIDENCE = "Insufficient Evidence"


class CoverageLevel(str, Enum):
    COVERED = "Covered"
    PARTIAL = "Partial"
    MISSING = "Missing"
    INSUFFICIENT_EVIDENCE = "Insufficient Evidence"


class Priority(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class ImplementationDepth(str, Enum):
    """Module 1 implementation depth scale — distinct from Coverage.

    Five-stage Institutionalization Scale, each stage a strictly stronger,
    unambiguous claim than the last:

      Unaddressed      → the dimension is not meaningfully mentioned at all.
      Emerging         → dimension-relevant terms appear AND the document
                         signals intent — something is going to be
                         established/done — but nobody owns it and no duty
                         has been created.
      Delegated        → the dimension has an owner or a duty, but not a
                         working regime: either a named institution carries
                         it (Assigned, T2) or a single binding duty exists
                         with nothing enforcing it (Obligatory, T3).
      Operationalized  → a concrete mechanism exists (a named body/authority
                         is assigned, or a documented reporting/process
                         obligation is imposed) but no enforcement,
                         monitoring, audit, or redress evidence backs it.
      Institutionalized → a concrete mechanism AND real teeth — enforcement,
                         monitoring, audit, or redress evidence — are both
                         present.

    Computed deterministically in compute_implementation_depth() from (a)
    Coverage level and (b) the operational-mechanism/enforcement signals
    found in the SAME evidence that grounds the Coverage verdict (never a
    free LLM judgment call, and never scored from a different evidence pool
    than the one that justified Coverage — see gap_analyzer.py).
    """

    UNADDRESSED = "Unaddressed"
    EMERGING = "Emerging"
    DELEGATED = "Delegated"
    DEVELOPING = "Operationalized"
    ESTABLISHED = "Institutionalized"


class ModuleCitation(BaseModel):
    """A single verified citation attached to a Module 1 or Module 2 field."""

    quote: str = ""
    chunk_id: str = ""
    source: str = ""  # framework name or "Uploaded Document"
    source_type: str = "framework"  # "document" | "framework"
    # Which uploaded document the chunk came from (multi-document workspaces,
    # e.g. NAIS vs the Model AI Governance Framework). None for framework
    # citations and for older single-document runs.
    document_name: str | None = None
    page_number: int | None = None
    claim: str = ""
    verified: bool = False
    no_citation: bool = False
    verification: dict[str, Any] | None = None


class Module1Evaluation(BaseModel):
    """Module 1 — Governance Dimension Evaluation (what the document says)."""

    dimension: str = ""
    coverage: CoverageLevel = CoverageLevel.MISSING
    gap_detected: bool = True
    reason_flagged: str = ""
    coverage_reasoning: str = ""
    # Fully Covered tier only: concrete examples from the uploaded document
    # that led to the Covered conclusion (substantive/theoretical, not
    # verbatim citations). Populated by the LLM, displayed only when
    # coverage == Covered (enforced in the frontend by coverage tier).
    coverage_example: str = ""
    # Inputs to the deterministic coverage ladder check (R1 explicit-
    # commitment floor / R2 implementation-commitment raise) — persisted so
    # the explainability layer can show WHY a coverage label was validated.
    principle_acknowledged: bool = True
    operational_mechanisms: list[str] = []
    implementation_depth: ImplementationDepth = ImplementationDepth.UNADDRESSED
    depth_reasoning: str = ""
    document_evidence: list[ModuleCitation] = []
    framework_evidence: list[ModuleCitation] = []


class InternationalExample(BaseModel):
    """A single real, cited international practice (Fully Covered tier).

    Anti-fabrication rule: an example is only kept when it carries a real
    chunk_id that exists in the vector store — never an invented country
    practice. Code drops examples the model could not ground.
    """

    practice: str = ""
    country_or_source: str = ""
    reference: str = ""
    # One sentence relating the practice to what the assessed document
    # already does, so the example reads as a next step, not a digression.
    alignment: str = ""
    citation: ModuleCitation | None = None


class BestPractices(BaseModel):
    """Fully Covered tier Module 2 payload — replaces Recommendations/Priority."""

    opening: str = ""
    # Renamed from 'optional_enhancements' — "optional" reads as "ignore" to
    # governments. These are strengthening opportunities for future revisions.
    future_strengthening_opportunities: list[str] = []
    international_examples: list[InternationalExample] = []


class Module2Recommendation(BaseModel):
    """Module 2 — Recommendations & Alignment (what to do about it).

    priority is null for the Fully Covered tier (nothing to prioritise) and
    for INSUFFICIENT_EVIDENCE. best_practices is set ONLY for Fully Covered
    dimensions; for Partial/Missing it is None.
    """

    dimension: str = ""
    recommendations: list[str] = []
    priority: Priority | None = None
    international_standard_reference: str = ""
    framework_synthesis: str = ""
    # Structured framework synthesis — Consensus / Differences / Overall
    # assessment. `framework_synthesis` above is the composed legacy string
    # ("Consensus: ...\n\nDifferences: ...\n\nOverall assessment: ...") kept for
    # every existing consumer; these three fields are the structured source.
    framework_synthesis_consensus: str = ""
    framework_synthesis_differences: str = ""
    framework_synthesis_overall_assessment: str = ""
    standard_citations: list[ModuleCitation] = []
    best_practices: BestPractices | None = None


class RetrievedEvidence(BaseModel):
    chunk_id: str
    text: str
    page_number: int | None = None
    source_framework: str
    # Source uploaded document for document-type evidence (multi-doc).
    document_name: str | None = None
    similarity_score: float | None = None
    section_title: str | None = None
    verified: bool = False
    verification: dict[str, Any] | None = None


class Module3Phase(BaseModel):
    """A single implementation phase in the Module 3 roadmap."""

    phase: str = ""  # "Phase 1" / "Phase 2"
    timeline: str = ""  # e.g. "0-12 months" — deterministic
    # Deterministic estimate rationale (code-computed, never LLM guesswork):
    # which signals (coverage tier, existing mechanisms, depth, agency
    # grounding, scope) produced the range, so the timeline is auditable.
    timeline_reasoning: str = ""
    objective: str = ""  # what this phase accomplishes
    steps: list[str] = []  # sequential implementation steps


class Module3Implementation(BaseModel):
    """Module 3 — Implementation Roadmap (what to do to close the gap).

    Present ONLY for Partial/Missing dimensions (enforced in code by the
    coverage-tier conditional — Fully Covered dimensions never run the
    Module 3+4 call and keep this field None).
    """

    dimension: str = ""
    coverage_tier: str = ""  # "Partial" | "Missing" (persisted tier)
    phases: list[Module3Phase] = []
    # Responsible Agency — the highest-fabrication-risk field. Must be
    # grounded in an institution the input document already names or clearly
    # implies; when none exists the field states "Not specified by policy —
    # implementation responsibility should be assigned by the adopting
    # government." (never a plausible-sounding invented agency).
    responsible_agency: str = ""
    # "document_named" | "document_implied" | "none_identified" — how the
    # agency was grounded (code-verified, see gap_analyzer).
    responsible_agency_grounding: str = "none_identified"
    documentation_requirements: list[str] = []
    monitoring_checklist: list[str] = []
    citations: list[ModuleCitation] = []  # module_3_implementation sources


class IncidentMatch(BaseModel):
    """A single matched incident for Module 4 — grounded in a real curated
    incident-record chunk (never LLM-fabricated).

    The write-up (Potential Consequence / Lessons Learned / Mitigation) is
    LLM-generated around the matched incident; the MATCH itself is
    retrieval-only + dimension-grounded (see gap_analyzer), and the incident
    citation is verified against the vector store like every other citation.
    """

    incident_name: str = ""
    source: str = ""  # curated incident record name
    what_happened: str = ""  # the incident's concrete facts, from the citation
    dimension_relevance: str = ""  # why it relates to this dimension
    potential_consequence: str = ""
    lessons_learned: str = ""
    mitigation: str = ""
    citation: ModuleCitation | None = None


class Module4CaseIntelligence(BaseModel):
    """Module 4 — Case Intelligence for one dimension.

    Present ONLY when a genuinely relevant incident match exists (code
    gate: the incident chunk must pass the dimension-grounding check and
    resolve to a real module_4_incident chunk). Never force-included to fill
    the section.
    """

    dimension: str = ""
    matched: bool = False
    incident_matches: list[IncidentMatch] = []
    summary: str = ""


class FrameworkPositionRaw(BaseModel):
    framework: str
    position: str
    supporting_text: str = ""
    chunk_id: str = ""
    verified: bool = False
    failure: str = ""


class GovernanceGap(BaseModel):
    dimension: str
    coverage: CoverageLevel = CoverageLevel.MISSING
    gap_found: bool = True
    evidence: list[RetrievedEvidence] = []
    reason_flagged: str
    recommendation: str
    risk_level: RiskLevel = RiskLevel.INSUFFICIENT_EVIDENCE
    risk_reason: str = ""
    # Deterministic description of WHY this dimension carries risk, derived
    # from the evidence profile. Kept on the gap so the final cross-dimension
    # risk pass re-applies it instead of falling back to the generic
    # "Core/Supporting dimension X is partially addressed" sentence.
    risk_basis: str = ""
    potential_consequence: str = ""
    un_recommendation: str = ""
    framework_synthesis: str = ""
    framework_positions: list[FrameworkPositionRaw] = []
    confidence_score: float = 0.0
    confidence_method: str = ""
    coverage_reasoning: str = ""
    # ── Mechanism breadth: the COVERAGE axis ──
    # Which framework-required mechanisms this dimension actually provides,
    # mapped to the normative tier (0-4) of the strongest provision supplying
    # each, plus the ones nothing supplies. Deliberately independent of the
    # force verdict: breadth answers "how much of what this dimension needs is
    # addressed at all", force answers "with what authority". Keeping them
    # apart is what lets a reader see a document that addresses nearly
    # everything and binds almost none of it.
    mechanisms_present: dict[str, int] = {}
    mechanisms_absent: list[str] = []
    # The absent mechanisms, most widely expected first, each with the number
    # of reference instruments that name it. Ordering only — it decides which
    # gap a reader is shown at the top, never what the verdict is. A ministry
    # asking "what do I fix first" is asking this question, and a flat list of
    # absences cannot answer it.
    priority_gaps: list[dict[str, Any]] = []
    #: How many instruments the counts above were taken over.
    framework_corpus_size: int = 0
    # How much evidence stands behind THIS cell: strong | moderate |
    # insufficient | none, with the reason. A verdict resting on 171 binding
    # provisions and one resting on 1 render identically without it, so a
    # reader cannot tell which to verify before quoting. Per-dimension
    # external validation reaches 38% of cells; this is how the other 62%
    # tell you what they are worth.
    evidence_confidence: str = ""
    evidence_confidence_reason: str = ""
    # Whether the mechanisms above were adjudicated or are raw cue matches
    # ("applied" | "unavailable" | "" when never asked). The fallback
    # over-reports presence, which can only raise depth, so a run carrying
    # "unavailable" is provisional and must not stand in for a complete one.
    mechanism_adjudication: str = ""
    # ── Module 1 + Module 2 (expanded analysis) ──
    implementation_depth: ImplementationDepth = ImplementationDepth.UNADDRESSED
    depth_reasoning: str = ""
    module_1: Module1Evaluation | None = None
    module_2: Module2Recommendation | None = None
    # ── Module 3 (Implementation Roadmap) + Module 4 (Case Intelligence) ──
    # Conditional by coverage tier (enforced in code, never LLM judgment):
    #   Fully Covered → BOTH None (no Module 3+4 call fired at all).
    #   Partial/Missing → module_3 populated; module_4 populated ONLY when a
    #   genuinely relevant incident match exists.
    module_3: Module3Implementation | None = None
    module_4: Module4CaseIntelligence | None = None
    # Set ONLY when the dimension could not be analysed at all (e.g. LLM
    # quota exhaustion / provider failure). Distinct from INSUFFICIENT_EVIDENCE
    # coverage, which is a genuine finding that no evidence supports a verdict.
    analysis_error: str | None = None
    # Article/recital/section numbers the narrative cited that could NOT be
    # located in the retrieved source text. Measured on real runs as the
    # weakest link in the output: article numbers were reliable, but recital
    # and section numbers were confabulated — a plausible number within a
    # couple of the correct one, attached to a real obligation the model knew
    # existed. Surfaced rather than silently dropped so a reader knows which
    # specific numbers not to rely on.
    # Real provisions the model recalled from memory: present in the uploaded
    # document but absent from the evidence retrieved for this dimension.
    unverifiable_citations: list[str] = []
    # Numbers that appear NOWHERE in the uploaded document — invented outright.
    # Separate from the above because the two need different reader responses.
    fabricated_citations: list[str] = []


class EvidenceItem(BaseModel):
    chunk_id: str
    text: str
    page_number: int | None = None
    section_title: str | None = None
    source_framework: str
    similarity_score: float | None = None
    aspect: str = ""
    claim: str = ""
    is_document: bool = True
    verified: bool = False
    verification: dict[str, Any] | None = None


class DimensionProfile(BaseModel):
    dimension: str
    definition: str
    aspects: list[str]
    is_core: bool = False


class EvidenceAgreement(str, Enum):
    SUPPORTING = "supporting"
    CONFLICTING = "conflicting"
    DUPLICATE = "duplicate"
    INDEPENDENT = "independent"
    WEAK = "weak"


class EvidencePair(BaseModel):
    item_a_id: str
    item_b_id: str
    agreement: EvidenceAgreement
    score: float
    reason: str = ""


class CalibratedConfidence(BaseModel):
    overall: float = 0.0
    evidence_quality_factor: float = 0.0
    evidence_diversity_factor: float = 0.0
    evidence_agreement_factor: float = 0.0
    retrieval_stability_factor: float = 0.0
    citation_strength_factor: float = 0.0
    cross_source_agreement: float = 0.0
    coverage_completeness_factor: float = 0.0
    method: str = ""

    def geometric_mean(self) -> float:
        factors = [
            max(f or 0, 0.001)
            for f in [
                self.evidence_quality_factor,
                self.evidence_diversity_factor,
                self.evidence_agreement_factor,
                self.retrieval_stability_factor,
                self.citation_strength_factor,
                self.cross_source_agreement,
                self.coverage_completeness_factor,
            ]
        ]
        product = 1.0
        for f in factors:
            product *= f
        return round(product ** (1.0 / len(factors)), 4)
