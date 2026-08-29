from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class GovernanceMaturityLevel(int, Enum):
    ABSENT = 0
    GENERAL_ACKNOWLEDGEMENT = 1
    GOVERNANCE_OBJECTIVES_DEFINED = 2
    OPERATIONAL_MECHANISMS = 3
    IMPLEMENTATION_AND_OVERSIGHT = 4
    CONTINUOUS_MONITORING_AND_ENFORCEMENT = 5


class EvidenceStrength(str, Enum):
    NOT_DEMONSTRATED = "Not Demonstrated"
    WEAKLY_DEMONSTRATED = "Weakly Demonstrated"
    IMPLICITLY_ADDRESSED = "Implicitly Addressed"
    EXPLICITLY_ADDRESSED = "Explicitly Addressed"
    STRONGLY_OPERATIONALISED = "Strongly Operationalised"


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


class GovernanceMaturity(str, Enum):
    """Module 1 governance maturity scale — distinct from Coverage.

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

    Computed deterministically in compute_governance_maturity() from (a)
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
    source: str = ""            # framework name or "Uploaded Document"
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
    governance_maturity: GovernanceMaturity = GovernanceMaturity.UNADDRESSED
    maturity_reasoning: str = ""
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
    semantic_score: float | None = None


class Module3Phase(BaseModel):
    """A single implementation phase in the Module 3 roadmap."""

    phase: str = ""                # "Phase 1" / "Phase 2"
    timeline: str = ""             # e.g. "0-12 months" — deterministic
    # Deterministic estimate rationale (code-computed, never LLM guesswork):
    # which signals (coverage tier, existing mechanisms, maturity, agency
    # grounding, scope) produced the range, so the timeline is auditable.
    timeline_reasoning: str = ""
    objective: str = ""            # what this phase accomplishes
    steps: list[str] = []          # sequential implementation steps


class Module3Implementation(BaseModel):
    """Module 3 — Implementation Roadmap (what to do to close the gap).

    Present ONLY for Partial/Missing dimensions (enforced in code by the
    coverage-tier conditional — Fully Covered dimensions never run the
    Module 3+4 call and keep this field None).
    """

    dimension: str = ""
    coverage_tier: str = ""        # "Partial" | "Missing" (persisted tier)
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
    citations: list[ModuleCitation] = []   # module_3_implementation sources


class IncidentMatch(BaseModel):
    """A single matched incident for Module 4 — grounded in a real curated
    incident-record chunk (never LLM-fabricated).

    The write-up (Potential Consequence / Lessons Learned / Mitigation) is
    LLM-generated around the matched incident; the MATCH itself is
    retrieval-only + dimension-grounded (see gap_analyzer), and the incident
    citation is verified against the vector store like every other citation.
    """

    incident_name: str = ""
    source: str = ""               # curated incident record name
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


class EvidenceInterpretation(BaseModel):
    dimension: str
    explicit_evidence: list[str] = []
    implicit_evidence: list[str] = []
    demonstrated_capability: str = ""
    absent_capability: str = ""
    strong_evidence: list[str] = []
    weak_evidence: list[str] = []
    contradictory_evidence: list[str] = []
    evidence_strength: EvidenceStrength = EvidenceStrength.NOT_DEMONSTRATED
    interpretation_summary: str = ""


class MaturityAssessment(BaseModel):
    dimension: str
    maturity_level: GovernanceMaturityLevel = GovernanceMaturityLevel.ABSENT
    maturity_label: str = "Absent"
    coverage: CoverageLevel = CoverageLevel.MISSING
    maturity_reasoning: str = ""
    level_justification: str = ""
    uncertainty_flags: list[str] = []
    false_negative_check: str = ""


class FrameworkSynthesisResult(BaseModel):
    dimension: str
    universal_requirements: list[str] = []
    framework_agreements: list[str] = []
    framework_differences: list[str] = []
    existing_mechanisms: list[str] = []
    missing_mechanisms: list[str] = []
    framework_specific_requirements: dict[str, list[str]] = {}
    synthesis: str = ""
    implementation_maturity_comparison: dict[str, list[str]] = {}


class PlausibilityReview(BaseModel):
    dimension: str
    original_maturity_level: int = 0
    validated_maturity_level: int = 0
    validated_coverage: CoverageLevel = CoverageLevel.MISSING
    plausibility_checks: list[str] = []
    adjustment_rationale: str = ""
    confidence_in_assessment: str = "Medium"
    uncertainty_acknowledged: list[str] = []


class PolicyRecommendation(BaseModel):
    dimension: str
    existing_strengths: str = ""
    governance_capability: str = ""
    remaining_limitations: str = ""
    missing_mechanisms: list[str] = []
    recommendations: list[str] = []
    smallest_effective_improvement: str = ""
    recommendation_rationale: str = ""


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
    evidence_quotes: list[str] = []
    aspects_addressed: list[str] = []
    aspects_missing: list[str] = []
    gap_analysis: str = ""
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
    # ── Module 1 + Module 2 (expanded analysis) ──
    governance_maturity: GovernanceMaturity = GovernanceMaturity.UNADDRESSED
    maturity_reasoning: str = ""
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
    # Fully Covered drift safeguard: True when the deterministic check found
    # gap-filling/recommendation language in a Covered dimension's own
    # framework_synthesis and auto-downgraded it to Partial for review. A
    # consumer (frontend, executive summary) should treat this as a review
    # state, NOT a normal Partial finding — it signals the Coverage label and
    # the generated content drifted apart.
    synthesis_drift_downgraded: bool = False
    # Ladder-raise review flag: True when the deterministic coverage ladder
    # (R1/R2) raised the LLM's raw verdict to a level its own
    # coverage_reasoning contradicts (the reasoning lists explicit gaps —
    # "does not establish", "no provisions", "lacks" — yet the raised
    # verdict says Covered/Partial). A review state, not an ordinary finding:
    # the ladder's own override is held to the same consistency discipline
    # as LLM output (mirror of synthesis_drift_downgraded).
    ladder_raise_review_flag: bool = False
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
    semantic_relevance: float = 0.0
    is_document: bool = True
    verified: bool = False
    verification: dict[str, Any] | None = None


class AspectGroup(BaseModel):
    aspect: str
    evidence: list[EvidenceItem] = []
    coverage_quality: float = 0.0
    coverage_estimate: str = "unknown"
    synthesized_claim: str = ""


class EvidenceGraph(BaseModel):
    dimension: str
    aspect_groups: list[AspectGroup] = []
    missing_aspects: list[str] = []
    evidence_quality_score: float = 0.0
    quality_factors: dict[str, float] = {}
    source_diversity_score: float = 0.0
    coverage_completeness: float = 0.0
    redundancy_ratio: float = 0.0
    total_chunks_retrieved: int = 0
    total_chunks_after_synthesis: int = 0


class DimensionProfile(BaseModel):
    dimension: str
    definition: str
    aspects: list[str]
    is_core: bool = False


class RetrievalResult(BaseModel):
    document_chunks: list[dict[str, Any]]
    framework_chunks: list[dict[str, Any]]
    retrieval_queries: list[str] = []
    retrieval_latency: float = 0.0
    total_candidates: int = 0


class VerificationStatus(str, Enum):
    SUPPORTS = "supports"
    PARTIALLY_SUPPORTS = "partially_supports"
    CONTRADICTS = "contradicts"
    IRRELEVANT = "irrelevant"
    UNVERIFIED = "unverified"


class CitationVerification(BaseModel):
    claim: str
    chunk_id: str
    chunk_text: str
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    confidence: float = 0.0
    reason: str = ""
    method: str = ""
    semantic_similarity: float | None = None
    nli_score: float | None = None
    keyword_overlap: float | None = None


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


class RetrievalStability(BaseModel):
    dimension: str
    num_retrievals: int = 3
    jaccard_similarity: float = 0.0
    kendall_tau: float = 0.0
    semantic_stability: float = 0.0
    score_variance: float = 0.0
    is_stable: bool = False


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
        import math
        product = 1.0
        for f in factors:
            product *= f
        return round(product ** (1.0 / len(factors)), 4)


class RetrievalMetrics(BaseModel):
    precision_at_1: float = 0.0
    precision_at_3: float = 0.0
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0
    recall_at_3: float = 0.0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    ndcg_at_10: float = 0.0
    coverage_recall: float = 0.0
    evidence_diversity: float = 0.0
    duplicate_rate: float = 0.0
    avg_retrieval_similarity: float = 0.0
    framework_retrieval_accuracy: float = 0.0
    policy_retrieval_accuracy: float = 0.0
    false_positive_rate: float = 0.0
    false_negative_rate: float = 0.0


class BenchmarkConfig(BaseModel):
    name: str
    enabled_features: dict[str, bool] = {}
    max_candidates: int = 30
    top_k_after_rerank: int = 10
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    nli_model: str = "cross-encoder/nli-deberta-v3-base"


class BenchmarkRun(BaseModel):
    run_id: str
    config: BenchmarkConfig
    per_dimension: dict[str, RetrievalMetrics] = {}
    aggregate: RetrievalMetrics = RetrievalMetrics()
    total_latency: float = 0.0
    memory_mb: float = 0.0
    rerank_latency: float = 0.0
    citation_quality: float = 0.0
    confidence_calibration: float = 0.0
    duplicate_reduction: float = 0.0


class DimensionNode(BaseModel):
    name: str
    parents: list[str] = []
    children: list[str] = []
    requires: list[str] = []
    required_by: list[str] = []


class DimensionGraph(BaseModel):
    nodes: dict[str, DimensionNode] = {}

    def add_relationship(self, parent: str, child: str, rel_type: str = "subsumes"):
        if parent not in self.nodes:
            self.nodes[parent] = DimensionNode(name=parent)
        if child not in self.nodes:
            self.nodes[child] = DimensionNode(name=child)
        if child not in self.nodes[parent].children:
            self.nodes[parent].children.append(child)
        if parent not in self.nodes[child].parents:
            self.nodes[child].parents.append(parent)
        if rel_type == "requires":
            if child not in self.nodes[parent].requires:
                self.nodes[parent].requires.append(child)
            if parent not in self.nodes[child].required_by:
                self.nodes[child].required_by.append(parent)

    def get_ancestors(self, name: str) -> list[str]:
        visited: set[str] = set()
        result: list[str] = []
        stack = [name]
        while stack:
            current = stack.pop()
            node = self.nodes.get(current)
            if node is None:
                continue
            for p in node.parents:
                if p not in visited:
                    visited.add(p)
                    result.append(p)
                    stack.append(p)
        return result

    def get_descendants(self, name: str) -> list[str]:
        visited: set[str] = set()
        result: list[str] = []
        stack = [name]
        while stack:
            current = stack.pop()
            node = self.nodes.get(current)
            if node is None:
                continue
            for c in node.children:
                if c not in visited:
                    visited.add(c)
                    result.append(c)
                    stack.append(c)
        return result

    def has_path(self, source: str, target: str) -> bool:
        return target in self.get_descendants(source)
