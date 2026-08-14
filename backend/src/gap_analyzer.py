from __future__ import annotations

import os
import re
import threading
import time
import uuid
import structlog
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from pydantic import BaseModel, Field

from src.vectorstore import VectorStore
from src.provider_router import get_provider, generate_with_retry, print_debug_summary
from src.llm_provider import LLMProvider
from src.models import (
    GovernanceGap, CoverageLevel, RiskLevel, Priority,
    RetrievedEvidence, CalibratedConfidence,
    GovernanceMaturity, ModuleCitation, Module1Evaluation, Module2Recommendation,
    BestPractices, InternationalExample,
    Module3Implementation, Module3Phase, Module4CaseIntelligence, IncidentMatch,
)
from src.retrieval import RetrievalPipeline, ModuleRetrievalResult, Module34RetrievalResult
from src.consistency import (
    ConsistencyValidator,
    detect_covered_synthesis_drift,
    COVERED_SYNTHESIS_DOWNGRADE_THRESHOLD,
)
from src.nli_verifier import NLIVerifier
from src.evidence_agreement import compute_evidence_agreement_score
from src import analysis_prompts
from src.deterministic import (
    compute_governance_maturity,
    validate_coverage_deterministic,
    _chunk_matches_dimension,
    _has_keyword,
    is_low_information_fragment,
    NAMED_BODY_KEYWORDS,
)
from src.verify import verify_citation
from src.framework_router import (
    resolve_dimension_frameworks,
    resolve_frameworks,
    resolve_regional_frameworks,
)

# Bounded concurrency for the per-dimension analysis loop. The 8 dimensions
# used to run strictly sequentially (up to 16 LLM calls back to back); now
# they run in a small worker pool (default 3 in flight, env-tunable) while
# the shared RPM throttle in provider_router paces the actual request rate
# underneath — the wall-clock win without exceeding the free-tier quota.
ANALYSIS_MAX_CONCURRENCY = int(os.getenv("ANALYSIS_MAX_CONCURRENCY", "3"))


class _DimensionRunState:
    """Thread-shared mutable state for the bounded-parallel dimension loop.

    Every counter/list the per-dimension workers touch lives here under a
    lock, so a parallel run is observably identical to the old sequential
    one: same totals (llm_call_count, latency, retrieved pool), same
    per-dimension chunk counts, same callback contract.
    """

    def __init__(self, callback: Callable | None = None) -> None:
        self.callback = callback
        self.lock = threading.Lock()
        self.all_retrieved: list[dict[str, Any]] = []
        self.doc_chunks_per_dimension: dict[str, int] = {}
        self.llm_call_count = 0
        self.total_llm_latency = 0.0

# Words that never denote an institution when they appear capitalized in a
# recommendation (used by the Module 2 → Module 3 agency cross-reference).
_MODULE2_AGENCY_SKIP = {
    "the", "and", "ai", "india", "task", "phase", "step", "such", "in",
    "of", "to", "a", "an", "data", "public", "national", "new", "this",
    "standard", "standards", "body", "bodies", "each", "for", "with",
    "across", "government", "all", "high", "risk", "use", "using", "ml",
}

# Organizational designators. A multi-word capitalized phrase is only
# treated as an institution when it contains one of these — otherwise a
# generic noun phrase like "Digital Public Infrastructure" or "Generative
# AI" (which appears verbatim in policy documents all the time) would be
# mistaken for a body being tasked. Single-token acronyms ("BIS", "CDEI")
# and CamelCase short forms ("MeitY") are handled separately by the
# capital-heavy pattern and do not need a designator.
_MODULE2_AGENCY_DESIGNATORS = {
    "ministry", "department", "bureau", "board", "authority", "commission",
    "agency", "institute", "council", "office", "foundation", "centre",
    "center", "directorate", "secretariat", "committee", "division",
    "cell", "administration", "regulator", "parliament", "cabinet",
    "task force",
}


def _extract_document_grounded_institutions(
    recommendations: list[str],
    document_text: str,
) -> list[str]:
    """Deterministically find institutions Module 2 recommendations name.

    Returns at most two capitalized institution-like phrases (multi-word
    names like "Bureau of Indian Standards", then capital-heavy tokens like
    "MeitY" / "BIS") that appear VERBATIM in the document text — so a name
    is only ever surfaced when the document genuinely contains it. Any
    ambiguous or generic capitalized phrase is dropped.
    """
    doc_lower = document_text.lower()
    found: list[str] = []
    for rec in recommendations:
        # Multi-word capitalized phrases first ("Bureau of Indian Standards").
        for m in re.finditer(
            r"\b[A-Z][a-zA-Z&.'\-]+(?:\s+(?:of\s+)?[A-Z][a-zA-Z&.'\-]+){1,3}\b",
            rec,
        ):
            phrase = m.group(0).strip()
            first = phrase.split()[0].lower()
            if first in _MODULE2_AGENCY_SKIP:
                continue
            # Designator gate: a multi-word capitalized phrase is only an
            # institution if it contains an organizational designator
            # ("Bureau of Indian Standards" ✓, "Generative AI" ✗,
            # "Digital Public Infrastructure" ✗).
            if not any(
                tok.lower() in _MODULE2_AGENCY_DESIGNATORS
                for tok in phrase.split()
            ):
                continue
            if phrase.lower() in doc_lower and phrase not in found:
                found.append(phrase)
        if len(found) >= 2:
            break
    if len(found) < 2:
        # Single capital-heavy tokens: all-caps acronyms ("BIS", "CDEI") and
        # CamelCase names with an internal capital ("MeitY", "OpenAI"). The
        # internal-capital pattern is what keeps ordinary capitalized words
        # like "Governance" or "Task" from being mistaken for institutions.
        for rec in recommendations:
            for m in re.finditer(
                r"\b[A-Z]{2,}[A-Za-z]*\b|\b[A-Z][a-z]+[A-Z][a-zA-Z]*\b",
                rec,
            ):
                token = m.group(0)
                low = token.lower()
                if low in _MODULE2_AGENCY_SKIP or len(low) <= 1:
                    continue
                if low in doc_lower and token not in found:
                    found.append(token)
            if len(found) >= 2:
                break
    return found[:2]

logger = structlog.get_logger()


GOVERNANCE_DIMENSIONS = [
    "Transparency",
    "Accountability",
    "Privacy",
    "Safety",
    "Human Autonomy",
    "Inclusivity",
    "Fairness",
    "Environmental Sustainability",
]

FALLBACK_TOP_K = int(os.getenv("FALLBACK_RETRIEVAL_TOP_K", "3"))
PRIMARY_TOP_K = int(os.getenv("PRIMARY_RETRIEVAL_TOP_K", "5"))

CORE_DIMENSIONS = {"Transparency", "Accountability", "Privacy", "Safety"}

DIMENSION_CLUSTERS = [
    {"Transparency", "Accountability"},
    {"Privacy", "Safety"},
    {"Fairness", "Inclusivity"},
    {"Human Autonomy", "Environmental Sustainability"},
]

COVERAGE_RANK = {"Covered": 0, "Partial": 1, "Missing": 2}

# Fully Covered tier: fixed opening line for the Best Practices block.
# Code-emitted (deterministic), never LLM-written.
BEST_PRACTICES_OPENING = (
    "This policy already aligns strongly with international governance "
    "expectations. The following international practices may further "
    "strengthen future revisions, but no critical governance gaps were "
    "identified."
)

DOC_RETRIEVE_K = int(os.getenv("DOC_RETRIEVE_K", "15"))

# Sentinel the combined prompt instructs the model to emit when no context
# line supports a citation. It is an explicit "no citation" state — never a
# real chunk id — so verification must not treat it as a lookup failure.
NO_CITATION_SENTINELS = {
    "insufficient evidence for citation",
    "insufficient evidence",
    "no citation available",
    "no citation",
    "no supporting passage",
    "not available",
    "none",
    "n/a",
    "na",
}


class GapAnalysisResult(BaseModel):
    analysis_id: str
    workspace_id: str
    document_name: str
    frameworks_used: list[str]
    governance_gaps: list[GovernanceGap]
    summary: str
    total_retrieved: int
    retrieval_frameworks: list[str]
    similarity_scores: list[float]
    llm_latency: float = 0.0
    total_processing_time: float = 0.0
    status: str = "complete"
    generated_by: dict[str, str] = Field(
        default_factory=lambda: {"provider": "unknown", "tier": "unknown"}
    )
    consistency_report: dict[str, Any] | None = None
    # Actual LLM calls made for this analysis: 8 Module 1+2 calls (one per
    # dimension) + one conditional Module 3+4 call per Partial/Missing
    # dimension. Fully Covered dimensions cost exactly one call. Reported so
    # quota usage is observable (the user expects ~8 + up to 8 = up to 16
    # worst case, fewer in practice).
    llm_call_count: int = 0
    # Per-coverage-tier output statistics (module_2 payload char counts) for
    # reporting the token reduction of the Fully Covered tier.
    tier_stats: dict[str, dict[str, Any]] | None = None
    # Executive decision analytics for the whole analysis — powers the summary
    # card, future dashboard visualisations (pie charts, maturity gauges,
    # country comparisons) and the research paper's evaluation section.
    decision_analytics: dict[str, Any] | None = None


# Ordinal ordering of GovernanceMaturity stages (low → high). Used ONLY for
# ordering, comparisons, and the weakest-dimension staged-maturity rule —
# never averaged (stages are ordinal categories; a mean of ranks rounded to a
# label is statistically invalid).
MATURITY_RANK = {
    GovernanceMaturity.AD_HOC: 0,
    GovernanceMaturity.DEVELOPING: 1,
    GovernanceMaturity.DEFINED: 2,
    GovernanceMaturity.MANAGED: 3,
    GovernanceMaturity.OPTIMIZED: 4,
}

MAX_MATURITY_RANK = max(MATURITY_RANK.values())

# Reverse map: rank → stage label, for weakest-dimension staging.
RANK_TO_LABEL = {rank: stage.value for stage, rank in MATURITY_RANK.items()}

# Priority rank (high → low) for sorting "most urgent first".
PRIORITY_RANK = {
    Priority.CRITICAL: 0,
    Priority.HIGH: 1,
    Priority.MEDIUM: 2,
    Priority.LOW: 3,
}


def compute_decision_analytics(gaps: list[GovernanceGap]) -> dict[str, Any]:
    """Aggregate per-dimension verdicts into an executive decision summary.

    Deterministic (code, not LLM) so the numbers are reproducible for
    dashboards, cross-country comparisons, and evaluation reporting.
    """
    assessed = [
        g for g in gaps
        if g.coverage in (CoverageLevel.COVERED, CoverageLevel.PARTIAL, CoverageLevel.MISSING)
    ]

    covered = sum(1 for g in gaps if g.coverage == CoverageLevel.COVERED)
    partial = sum(1 for g in gaps if g.coverage == CoverageLevel.PARTIAL)
    missing = sum(1 for g in gaps if g.coverage == CoverageLevel.MISSING)
    insufficient = sum(
        1 for g in gaps
        if g.coverage == CoverageLevel.INSUFFICIENT_EVIDENCE and not g.analysis_error
    )
    failed = sum(1 for g in gaps if g.analysis_error)

    # ── Overall governance maturity ──────────────────────────────────────
    # CMMI-style staged maturity (weakest-dimension rule): an overall stage is
    # only claimable when EVERY assessed dimension reaches it — the policy is
    # as mature as its LEAST mature dimension. This is the standard threshold
    # logic of staged maturity models (CMMI), NOT a mean of ordinal ranks.
    # A continuous 0-100 composite index is provided alongside so the gradient
    # between stages is visible for dashboards.
    assessed_ranks = [MATURITY_RANK.get(g.governance_maturity, 0) for g in assessed]
    if assessed_ranks:
        weakest_rank = min(assessed_ranks)
        overall_maturity_label = RANK_TO_LABEL[weakest_rank]
        # Composite index: percentage of maximum achievable maturity across
        # the assessed dimensions (0-100, continuous for gauges/trends).
        maturity_index = round(
            100.0 * sum(assessed_ranks) / (MAX_MATURITY_RANK * len(assessed_ranks)), 1
        )
        # Full stage histogram (pie/histogram-ready).
        maturity_distribution = {
            label: sum(1 for r in assessed_ranks if r == rank)
            for rank, label in RANK_TO_LABEL.items()
        }
    else:
        overall_maturity_label = "Not Assessed"
        maturity_index = 0.0
        maturity_distribution = {label: 0 for label in RANK_TO_LABEL.values()}

    # ── Highest priority dimensions (Critical/High, most urgent first) ──
    high_priority = [
        g for g in gaps
        if g.module_2 is not None and g.module_2.priority in (Priority.CRITICAL, Priority.HIGH)
    ]
    high_priority.sort(key=lambda g: PRIORITY_RANK.get(g.module_2.priority, 9))
    highest_priority_dimensions = [g.dimension for g in high_priority]

    # ── Strongest dimension (highest maturity, confidence tie-break) ──
    strongest_dimension = ""
    if assessed:
        strongest = max(
            assessed,
            key=lambda g: (MATURITY_RANK.get(g.governance_maturity, 0), g.confidence_score),
        )
        strongest_dimension = strongest.dimension

    # ── Synthesis-drift review flags ───────────────────────────────────
    # Dimensions auto-downgraded from Covered to Partial because their own
    # framework_synthesis used gap-filling language. Consumers (frontend,
    # executive summary, dashboards) should surface these as "review" states,
    # not as ordinary Partial findings.
    drift_downgraded = [
        g.dimension for g in gaps if g.synthesis_drift_downgraded
    ]

    avg_confidence = round(
        sum(g.confidence_score for g in assessed) / len(assessed), 3
    ) if assessed else 0.0

    return {
        "covered": covered,
        "partial": partial,
        "missing": missing,
        "insufficient_evidence": insufficient,
        "analysis_failed": failed,
        "overall_governance_maturity": overall_maturity_label,
        # Weakest-dimension staged maturity (CMMI rule): min stage across
        # assessed dimensions.
        "maturity_index": maturity_index,
        "maturity_distribution": maturity_distribution,
        "assessed_dimensions": len(assessed),
        "average_confidence": avg_confidence,
        "highest_priority_dimensions": highest_priority_dimensions,
        "strongest_dimension": strongest_dimension,
        "synthesis_drift_downgraded": drift_downgraded,
        "synthesis_drift_downgraded_count": len(drift_downgraded),
    }


def compute_calibrated_confidence(
    evidence_list: list[RetrievedEvidence],
    evidence_graph: Any | None = None,
    evidence_pairs: list | None = None,
    retrieval_stability: Any | None = None,
    citation_pass_rate: float | None = None,
    coverage_level: CoverageLevel | None = None,
    dimension: str | None = None,
) -> tuple[float, str]:
    if not evidence_list:
        return 0.0, "No evidence: confidence=0"

    cal = CalibratedConfidence()

    similarity_scores = [
        e.similarity_score for e in evidence_list
        if e.similarity_score is not None and 0 <= e.similarity_score <= 1
    ]
    if similarity_scores:
        cal.evidence_quality_factor = round(sum(similarity_scores) / len(similarity_scores), 3)
    elif evidence_graph and hasattr(evidence_graph, "evidence_quality_score"):
        cal.evidence_quality_factor = evidence_graph.evidence_quality_score
    else:
        cal.evidence_quality_factor = 0.3

    unique_sources = len({e.source_framework for e in evidence_list if e.source_framework})
    total_evidence = len(evidence_list)
    if total_evidence > 0:
        cal.evidence_diversity_factor = round(min(1.0, unique_sources / max(5, total_evidence) * 2), 3)
    else:
        cal.evidence_diversity_factor = 0.0

    if evidence_pairs:
        cal.evidence_agreement_factor = compute_evidence_agreement_score(evidence_pairs)
    else:
        cal.evidence_agreement_factor = 0.5

    if retrieval_stability is not None:
        if retrieval_stability.is_stable:
            cal.retrieval_stability_factor = retrieval_stability.semantic_stability
        else:
            cal.retrieval_stability_factor = max(0.1, retrieval_stability.semantic_stability * 0.5)
    else:
        cal.retrieval_stability_factor = 0.5

    if citation_pass_rate is not None:
        cal.citation_strength_factor = round(citation_pass_rate, 3)
    else:
        verified_count = sum(1 for e in evidence_list if e.verified)
        if total_evidence > 0:
            cal.citation_strength_factor = round(verified_count / total_evidence, 3)
        else:
            cal.citation_strength_factor = 0.0

    if total_evidence > 0:
        cal.cross_source_agreement = round(
            unique_sources / max(total_evidence, 1), 3
        )
    else:
        cal.cross_source_agreement = 0.0

    if evidence_graph and hasattr(evidence_graph, "coverage_completeness"):
        cal.coverage_completeness_factor = evidence_graph.coverage_completeness
    elif coverage_level is not None:
        cal.coverage_completeness_factor = {
            CoverageLevel.COVERED: 0.8,
            CoverageLevel.PARTIAL: 0.5,
            CoverageLevel.MISSING: 0.3,
            CoverageLevel.INSUFFICIENT_EVIDENCE: 0.1,
        }.get(coverage_level, 0.3)
    else:
        cal.coverage_completeness_factor = 0.3

    cal.overall = cal.geometric_mean()
    cal.method = (
        f"GeoMean(quality={cal.evidence_quality_factor:.3f}, "
        f"diversity={cal.evidence_diversity_factor:.3f}, "
        f"agreement={cal.evidence_agreement_factor:.3f}, "
        f"stability={cal.retrieval_stability_factor:.3f}, "
        f"citation={cal.citation_strength_factor:.3f}, "
        f"cross_source={cal.cross_source_agreement:.3f}, "
        f"coverage={cal.coverage_completeness_factor:.3f})"
    )

    return cal.overall, cal.method


def compute_risk(
    coverage: CoverageLevel,
    dimension: str,
    other_gaps: list[GovernanceGap] | None = None,
) -> tuple[RiskLevel, str]:
    if coverage == CoverageLevel.INSUFFICIENT_EVIDENCE:
        return RiskLevel.INSUFFICIENT_EVIDENCE, "Insufficient evidence from reference frameworks."

    is_core = dimension in CORE_DIMENSIONS

    if coverage == CoverageLevel.COVERED:
        base = RiskLevel.LOW
        reason = "Policy adequately addresses this dimension."
    elif coverage == CoverageLevel.PARTIAL:
        if is_core:
            base = RiskLevel.MEDIUM
            reason = f"Core dimension '{dimension}' is only partially addressed."
        else:
            base = RiskLevel.LOW
            reason = f"Supporting dimension '{dimension}' is partially addressed."
    else:
        if is_core:
            base = RiskLevel.HIGH
            reason = f"Core dimension '{dimension}' is not addressed."
        else:
            base = RiskLevel.MEDIUM
            reason = f"Supporting dimension '{dimension}' is not addressed."

    if coverage != CoverageLevel.COVERED and other_gaps:
        cluster = next((c for c in DIMENSION_CLUSTERS if dimension in c), None)
        if cluster:
            any_gap = any(
                g.dimension in cluster
                and g.dimension != dimension
                and g.coverage != CoverageLevel.COVERED
                for g in other_gaps
            )
            if any_gap:
                if base == RiskLevel.LOW:
                    base = RiskLevel.MEDIUM
                elif base == RiskLevel.MEDIUM:
                    base = RiskLevel.HIGH
                reason += " Risk compounded by related dimension gaps."

    return base, reason


def resolve_priority(
    coverage: CoverageLevel,
    dimension: str,
    other_gaps: list[GovernanceGap] | None = None,
) -> Priority | None:
    """Deterministic coverage-tiered priority. Enforced in code — the LLM
    never decides priority.

    - Covered              -> None (nothing to prioritise)
    - Partial              -> Medium by default; escalates to High when a
                              related dimension in the same cluster is also
                              not fully covered (risk-compounding rule).
    - Missing              -> High by default; escalates to Critical when a
                              related cluster dimension is also not covered.
    - Insufficient Evidence -> None (no assessment possible).
    """
    if coverage in (CoverageLevel.COVERED, CoverageLevel.INSUFFICIENT_EVIDENCE):
        return None

    if coverage == CoverageLevel.PARTIAL:
        priority: Priority = Priority.MEDIUM
    else:  # MISSING
        priority = Priority.HIGH

    cluster = next((c for c in DIMENSION_CLUSTERS if dimension in c), None)
    if cluster and other_gaps:
        any_gap = any(
            g.dimension in cluster
            and g.dimension != dimension
            and g.coverage != CoverageLevel.COVERED
            for g in other_gaps
        )
        if any_gap:
            if priority == Priority.MEDIUM:
                priority = Priority.HIGH
            elif priority == Priority.HIGH:
                priority = Priority.CRITICAL

    return priority


# ── Deterministic implementation-timeline estimator (Module 3) ────────────
# The Module 3 prompt used to tell the model to pick a "realistic range"
# (e.g. "0-12 months") — a guess with no basis in the document, which the
# model simply echoed back. Timelines are now computed in code from signals
# the pipeline already derives deterministically, so the range is auditable
# rather than invented:
#   - coverage tier: Missing builds from scratch (longer); Partial extends an
#     existing mechanism (shorter).
#   - existing operational mechanisms in the document shorten the runway.
#   - governance maturity: Ad Hoc / Developing lengthen ramp-up; Managed /
#     Optimized shorten it.
#   - responsible-agency grounding: no named body means designation time;
#     a document-named owner shortens it.
#   - phase scope (step count) widens/narrows the range.
# Phase 2 chains after Phase 1 (sequential, not overlapping).

MATURITY_SLOW = {GovernanceMaturity.AD_HOC, GovernanceMaturity.DEVELOPING}
MATURITY_FAST = {GovernanceMaturity.MANAGED, GovernanceMaturity.OPTIMIZED}


def estimate_phase_timelines(
    coverage: CoverageLevel,
    operational_mechanisms: list[str],
    maturity: GovernanceMaturity | None,
    agency_grounding: str,
    step_counts: list[int],
) -> list[dict[str, str]]:
    """Deterministic, evidence-grounded implementation-timeline estimate.

    Returns one entry per phase: {"timeline": "0-12 months", "reasoning": str}.
    Phase 1 establishes the foundation; Phase 2 operationalises and monitors.
    Phase 2 is chained after Phase 1 (sequential, not overlapping). The
    reasoning string makes every adjustment visible, so the estimate is
    auditable instead of a magic number.
    """
    missing = coverage == CoverageLevel.MISSING
    base_p1_upper = 12 if missing else 6
    base_p2_len = 12 if missing else 6

    def _adjust(steps: int, apply_agency: bool) -> tuple[int, list[str]]:
        adj = 0
        reasons: list[str] = []
        if maturity in MATURITY_SLOW:
            adj += 3
            reasons.append(f"low maturity ({maturity.value}) lengthens ramp-up")
        elif maturity in MATURITY_FAST:
            adj -= 2
            reasons.append(f"high maturity ({maturity.value}) shortens the runway")
        if operational_mechanisms:
            adj -= 2
            reasons.append(
                f"{len(operational_mechanisms)} existing operational "
                f"mechanism(s) already in the document"
            )
        # Agency designation is a ONE-TIME Phase 1 set-up. Its cost lands in
        # Phase 1 only; Phase 2 chains after Phase 1, so the designation time
        # already propagates through the chain — applying it again to Phase 2
        # would double-count it.
        if apply_agency:
            if agency_grounding == "none_identified":
                adj += 3
                reasons.append("no responsible agency named — designation time included")
            elif agency_grounding == "document_named":
                adj -= 2
                reasons.append("responsible agency already named in the document")
            elif agency_grounding == "document_implied":
                adj -= 1
                reasons.append("responsible agency implied by the document")
        if steps >= 6:
            adj += 3
            reasons.append(f"large scope ({steps} steps)")
        elif steps <= 2:
            adj -= 1
            reasons.append(f"small scope ({steps} steps)")
        return adj, reasons

    out: list[dict[str, str]] = []
    prev_upper = 0
    tier_note = (
        "Missing tier — builds the mechanism from scratch"
        if missing
        else "Partial tier — extends the existing partial mechanism"
    )
    for idx, steps in enumerate(step_counts[:2], start=1):
        if idx == 1:
            lo = 0
            base_upper = base_p1_upper
        else:
            lo = prev_upper
            base_upper = prev_upper + base_p2_len
        adj, reasons = _adjust(steps, apply_agency=(idx == 1))
        upper = max(lo + 3, base_upper + adj)
        phase_note = (
            "Phase 1 establishes the foundation"
            if idx == 1
            else "Phase 2 operationalises and monitors"
        )
        reason_text = "; ".join(reasons) if reasons else "no adjusting factors"
        reasoning = f"{phase_note}; {tier_note}; {reason_text}."
        out.append({"timeline": f"{lo}-{upper} months", "reasoning": reasoning})
        prev_upper = upper
    return out


def build_framework_synthesis(
    framework_positions: list[Any],
    evidence_list: list[RetrievedEvidence],
) -> str:
    if not framework_positions:
        return ""

    seen_frameworks: set[str] = set()
    valid_positions = []
    for fp in framework_positions:
        fw = fp.framework if not isinstance(fp, dict) else fp.get("framework", "")
        chunk_id = fp.chunk_id if not isinstance(fp, dict) else fp.get("chunk_id", "")
        pos = fp.position if not isinstance(fp, dict) else fp.get("position", "")
        supporting = fp.supporting_text if not isinstance(fp, dict) else fp.get("supporting_text", "")
        if fw in seen_frameworks:
            continue
        has_chunk = any(e.chunk_id == chunk_id for e in evidence_list)
        if not has_chunk:
            continue
        seen_frameworks.add(fw)
        valid_positions.append((fw, pos, supporting))

    if not valid_positions:
        return ""

    parts: list[str] = []
    for fw, pos, supporting in valid_positions:
        part = f"{fw}: {pos}"
        if supporting:
            part += f' ("{supporting}")'
        parts.append(part)

    return " | ".join(parts)


class GapAnalyzer:
    def __init__(
        self,
        vector_store: VectorStore,
        provider: LLMProvider | None = None,
    ):
        self.vector_store = vector_store
        self.provider = provider or get_provider()

        embed_fn = vector_store.embedding_service.embed_query

        self.retrieval_pipeline = RetrievalPipeline(vector_store)
        self.consistency_validator = ConsistencyValidator()
        self.nli_verifier = NLIVerifier(embed_function=embed_fn)

    # ── Combined Module 1 + Module 2 LLM schema ─────────────────────────

    @staticmethod
    def _get_combined_module_schema() -> type[BaseModel]:
        class CitationSchema(BaseModel):
            chunk_id: str
            quote: str
            page_number: int | None = None

        class InternationalExampleSchema(BaseModel):
            practice: str
            country_or_source: str
            chunk_id: str
            quote: str
            page_number: int | None = None

        class FrameworkSynthesisSchema(BaseModel):
            # Structured synthesis — Consensus / Differences / Overall
            # assessment. NOT a per-framework summary ("NIST says..." is
            # summarization, forbidden). Consensus = what the frameworks
            # collectively require; Differences = where they diverge (rights
            # vs operational vs public-sector emphasis); Overall assessment =
            # how the uploaded policy aligns with those requirements.
            consensus: str
            differences: str
            overall_assessment: str

        class CombinedModuleSchema(BaseModel):
            dimension: str
            # Module 1 — Governance Dimension Evaluation
            coverage: str
            gap_detected: bool
            reason_flagged: str
            coverage_reasoning: str
            # Fully Covered tier only: document-grounded examples leading to
            # the Covered verdict (substantive/theoretical, not verbatim
            # quotes). Empty string for Partial/Missing.
            coverage_example: str = ""
            principle_acknowledged: bool
            operational_mechanisms: list[str]
            document_evidence: list[CitationSchema]
            framework_evidence: list[CitationSchema]
            # Module 2 — Recommendations & Alignment
            recommendations: list[str]
            priority: str
            # Fully Covered tier only (replaces recommendations/priority):
            future_strengthening_opportunities: list[str] = []
            international_examples: list[InternationalExampleSchema] = []
            international_standard_reference: str
            framework_synthesis: FrameworkSynthesisSchema
            standard_citations: list[CitationSchema]

        return CombinedModuleSchema

    # ── Citation verification for both module fields ────────────────────

    @staticmethod
    def _is_no_citation_entry(chunk_id: str, quote: str = "") -> bool:
        """True when the model emitted the 'no citation' sentinel instead of a
        real chunk id. The prompt allows this when no context line supports a
        claim — it is an honest decline, not a failed lookup."""
        def _norm(value: str) -> str:
            return (value or "").strip(" .,;:!?\"'").lower()

        cid = _norm(chunk_id)
        # Real chunk ids are UUIDs, so a startswith on the sentinel prefix is
        # safe here. The quote is a backstop only: use EXACT membership so a
        # legitimate verbatim quote that happens to begin "insufficient
        # evidence..." (e.g. audit text) is never misclassified.
        if cid in NO_CITATION_SENTINELS or cid.startswith("insufficient"):
            return True
        return _norm(quote) in NO_CITATION_SENTINELS

    def _verify_international_examples(
        self,
        examples: list[Any],
        label_map: dict[str, str] | None = None,
    ) -> list[InternationalExample]:
        """Verify each international example's chunk against the vector store.

        Anti-fabrication rule (Fully Covered tier): an example is kept ONLY
        when it carries a real chunk_id that exists in the vector store — the
        model can never invent a country practice. Examples with sentinel,
        empty, or nonexistent chunk ids are dropped (and logged, so drops are
        visible rather than silent). Reuses _verify_module_citations for the
        chunk existence + verification path.
        """
        verified: list[InternationalExample] = []
        if not examples:
            return verified

        # Extract the practice metadata, then run the chunk/quote pairs
        # through the same verification path as every other citation.
        pairs: list[tuple[str, str, dict[str, Any]]] = []
        citation_dicts: list[dict[str, Any]] = []
        for ex in examples:
            if isinstance(ex, dict):
                practice = ex.get("practice", "") or ""
                country = ex.get("country_or_source", "") or ""
                chunk_id = ex.get("chunk_id", "") or ""
                quote = ex.get("quote", "") or ""
                page = ex.get("page_number")
            else:
                practice = getattr(ex, "practice", "") or ""
                country = getattr(ex, "country_or_source", "") or ""
                chunk_id = getattr(ex, "chunk_id", "") or ""
                quote = getattr(ex, "quote", "") or ""
                page = getattr(ex, "page_number", None)

            if not practice.strip():
                continue
            # Same label→real-id translation every other citation path uses:
            # the model may echo a prompt label (PRAC-2) instead of the real
            # chunk id; without this, a PRAC-style id fails chunk lookup and
            # the example is silently dropped even though it was grounded.
            if label_map and chunk_id in label_map:
                chunk_id = label_map[chunk_id]
            pairs.append((practice, country, {"chunk_id": chunk_id, "quote": quote, "page_number": page}))
            citation_dicts.append({"chunk_id": chunk_id, "quote": quote, "page_number": page})

        citations = self._verify_module_citations(citation_dicts, source_type="framework")
        for (practice, country, _raw), citation in zip(pairs, citations):
            # Drop sentinel / empty / nonexistent-chunk entries — the model
            # declined or fabricated; neither may surface as a real practice.
            # NOTE: _verify_module_citations keeps the chunk_id on missing
            # chunks (marked unverified), so re-check existence explicitly.
            if citation.no_citation or not citation.chunk_id:
                continue
            if self.vector_store.get_chunk(citation.chunk_id) is None:
                continue
            verified.append(InternationalExample(
                practice=practice.strip(),
                country_or_source=country.strip(),
                reference=citation.source,
                citation=citation,
            ))
        dropped = len(examples) - len(verified)
        if dropped:
            logger.warning(
                "international_examples_filtered",
                generated=len(examples),
                kept=len(verified),
                dropped=dropped,
            )
        return verified

    def _verify_module_citations(
        self,
        citations: list[Any],
        default_source: str = "",
        source_type: str = "framework",
        document_total_pages: int | None = None,
    ) -> list[ModuleCitation]:
        verified_list: list[ModuleCitation] = []
        for c in citations:
            chunk_id = c.get("chunk_id", "") if isinstance(c, dict) else getattr(c, "chunk_id", "")
            quote = c.get("quote", "") if isinstance(c, dict) else getattr(c, "quote", "")
            page = c.get("page_number") if isinstance(c, dict) else getattr(c, "page_number", None)
            if self._is_no_citation_entry(chunk_id, quote):
                verified_list.append(ModuleCitation(
                    quote="", chunk_id="", source=default_source,
                    source_type=source_type, page_number=None,
                    no_citation=True,
                    verification={
                        "passed": False,
                        "method": "no_citation_available",
                        "failure_reason": (
                            "No supporting passage was found in the retrieved "
                            "context — no citation was fabricated."
                        ),
                    },
                ))
                continue
            if not chunk_id:
                verified_list.append(ModuleCitation(
                    quote=quote, chunk_id="", source=default_source,
                    source_type=source_type, verified=False,
                    verification={"passed": False, "failure_reason": "No chunk_id provided."},
                ))
                continue

            chunk = self.vector_store.get_chunk(chunk_id)
            if chunk is None:
                verified_list.append(ModuleCitation(
                    quote=quote, chunk_id=chunk_id, source=default_source,
                    source_type=source_type, verified=False,
                    verification={"passed": False, "failure_reason": "Chunk does not exist in vector store."},
                ))
                continue

            md = chunk.get("metadata", {}) or {}
            source = default_source or md.get("framework", "") or ""
            # Observability: a low-information glossary fragment (a term +
            # footnote number) can still be LLM-cited if it reached the prompt
            # — the ranking fix makes fragments last-resort, not impossible.
            # Log it so fragment wins stay visible in the logs.
            if is_low_information_fragment((chunk.get("text") or "")[:300]):
                logger.warning(
                    "fragment_chunk_cited",
                    chunk_id=chunk_id,
                    source_type=source_type,
                    quote_len=len(quote),
                )
            # Multi-document workspaces: tag the citation with the actual
            # uploaded document it came from so the report can distinguish
            # NAIS vs the Model AI Governance Framework (or any other input).
            doc_name = md.get("document_name", "") or ""
            if source_type == "document" and doc_name:
                source = doc_name
            result = verify_citation(
                chunk_id=chunk_id,
                claim_text=quote or "",
                page_number=page,
                source_framework=source,
                vector_store=self.vector_store,
                document_total_pages=document_total_pages,
                nli_verifier=self.nli_verifier if self.nli_verifier.is_available else None,
            )
            verified_list.append(ModuleCitation(
                quote=quote,
                chunk_id=chunk_id,
                source=source,
                source_type=source_type,
                document_name=doc_name or None,
                page_number=page,
                verified=result.passed,
                verification=result.to_dict(),
            ))
        return verified_list

    def _ensure_minimum_citations(
        self,
        citations: list[ModuleCitation],
        fallback_chunks: list[dict[str, Any]],
        claim_note: str,
        source_type: str,
        dimension: str = "",
    ) -> list[ModuleCitation]:
        """Guarantee a citation exists even for Missing findings, per spec:
        cite the specific framework text that establishes the requirement.

        Anti-fabrication guards (code, never LLM judgment):
          - source guard: a fallback chunk without a real framework name is
            skipped, so "Source: Unknown" can never appear on a citation.
          - dimension grounding: a fallback chunk must be topically about the
            given dimension (shared ladder check), so a passage with broad
            generic embedding similarity can never become a requirement
            citation for an unrelated dimension.
        """
        # A no_citation entry is the model honestly declining to fabricate —
        # it should NOT satisfy the minimum-citation guarantee. Only real
        # citations (verified or not) do. When everything is a decline, replace
        # the placeholders with deterministic requirement citations instead.
        if any(not c.no_citation for c in citations):
            return citations
        result: list[ModuleCitation] = []
        for c in fallback_chunks[:2]:
            chunk = self.vector_store.get_chunk(c.get("chunk_id", ""))
            if chunk is None:
                continue
            md = chunk.get("metadata", {}) or {}
            source = md.get("framework", "") or ""
            # Source guard: never attach a citation we cannot attribute to a
            # named source — "Source: Unknown" must never reach a user.
            if not source:
                continue
            text = (c.get("text") or "")[:300]
            # Substance gate: a glossary/index fragment (a term + footnote
            # number like "Explainability15") carries no real sentence content
            # and must never become a requirement citation, even when it ranks
            # on embedding similarity.
            if is_low_information_fragment(text):
                logger.info(
                    "low_information_fragment_skipped",
                    chunk_id=c.get("chunk_id", ""),
                    dimension=dimension,
                    source="deterministic_fallback",
                )
                continue
            # Dimension grounding: only attach a chunk topically about THIS
            # dimension. An off-topic passage with broad embedding similarity
            # (e.g. a UN advisory-body participation paragraph) can never
            # become a requirement citation for an unrelated dimension.
            if dimension and not _chunk_matches_dimension(text, dimension):
                continue
            # Deterministically attached requirement citation. The quote IS the
            # chunk's own text, so a normal verify would trivially pass and show
            # a misleading green badge — mark it as auto-attached instead.
            result.append(ModuleCitation(
                quote=text,
                chunk_id=c["chunk_id"],
                source=source,
                source_type=source_type,
                page_number=c.get("page_number"),
                claim=claim_note,
                verified=False,
                verification={
                    "passed": False,
                    "method": "deterministic_fallback",
                    "failure_reason": "Auto-attached requirement citation — passage copied from the top retrieved chunk (not LLM-grounded).",
                },
            ))
            if len(result) >= 2:
                break
        # Keep the honest no_citation entries only when there is nothing to
        # attach (e.g. no chunks retrieved at all).
        return result if result else citations

    def _ground_module3_citations(
        self,
        citations: list[ModuleCitation],
        chunk_pool: list[dict[str, Any]],
        dimension: str,
        phases_count: int,
    ) -> list[ModuleCitation]:
        """Dimension-grounding gate for Module 3 implementation citations.

        The Module 3 implementation-source corpus is framework-only and can be
        thin for a given dimension (e.g. Environmental Sustainability): the
        top-ranked chunks are generic assurance/risk-assessment boilerplate
        the LLM cites because they rank first — verified-but-irrelevant
        citations, which are worse than honest absence. Same discipline as the
        Module 4 matching step: a citation is kept only when its chunk is
        topically about THIS dimension (shared _chunk_matches_dimension gate).

        Dropped slots are re-filled deterministically from the best
        dimension-topical chunks in the retrieved pool (the uploaded document
        first — the substantive dimension content usually lives there when the
        framework-only corpus is thin — then the Module 3 framework sources),
        guarded exactly like _ensure_minimum_citations: a real named source
        is required, glossary fragments and TOC/preamble fragments are
        skipped, and only dimension-topical chunks are attached (marked
        auto-attached, never "verified").

        Also normalizes the source of document-sourced citations: the verify
        path defaults to source_type="framework", which would leave a DOC-n
        citation with an empty source and render it invisible in the UI.
        """
        kept: list[ModuleCitation] = []
        real_kept = 0
        for c in citations:
            if c.no_citation:
                kept.append(c)
                continue
            if c.chunk_id:
                chunk = self.vector_store.get_chunk(c.chunk_id)
                if chunk:
                    text = chunk.get("text", "") or ""
                    md = chunk.get("metadata", {}) or {}
                    if not c.source and md.get("document_name"):
                        c.source = md["document_name"]
                        c.source_type = "document"
                        c.document_name = md["document_name"]
                    elif not c.source and md.get("framework"):
                        c.source = md["framework"]
                    if dimension and text and not _chunk_matches_dimension(
                        text, dimension
                    ):
                        logger.info(
                            "module3_citation_off_topic_dropped",
                            chunk_id=c.chunk_id,
                            dimension=dimension,
                        )
                        continue
            kept.append(c)
            real_kept += 1

        target = min(2, max(1, phases_count))
        used = {c.chunk_id for c in kept if c.chunk_id}
        for pool_chunk in chunk_pool:
            if real_kept >= target:
                break
            cid = pool_chunk.get("chunk_id")
            if not cid or cid in used:
                continue
            full_text = pool_chunk.get("text") or ""
            text = full_text[:300]
            # Substance gate: glossary/index fragments never become citations.
            if is_low_information_fragment(text):
                continue
            # TOC/preamble guard: a table-of-contents or cover-page fragment
            # ranks on broad vocabulary but carries no evidence content.
            # Deliberately narrow — "Executive Summary" is NOT excluded, since
            # a substantive summary section can carry the dimension's key
            # commitments and is legitimately citable.
            head = full_text[:200].lower()
            if "table of contents" in head or head.lstrip().startswith(
                "title page"
            ):
                continue
            # Dimension grounding: only attach chunks topically about THIS
            # dimension (checked on the full truncated text, not the quote).
            if dimension and not _chunk_matches_dimension(full_text, dimension):
                continue
            chunk = self.vector_store.get_chunk(cid)
            if chunk is None:
                continue
            md = chunk.get("metadata", {}) or {}
            source = md.get("framework", "") or ""
            doc_name = md.get("document_name", "") or ""
            # Source guard: never attach a citation without a real named source.
            if not source and not doc_name:
                continue
            used.add(cid)
            kept.append(ModuleCitation(
                quote=text,
                chunk_id=cid,
                source=source or doc_name,
                source_type="framework" if source else "document",
                document_name=doc_name or None,
                page_number=md.get("page_number") or pool_chunk.get("page_number"),
                verified=False,
                verification={
                    "passed": False,
                    "method": "deterministic_fallback",
                    "failure_reason": (
                        "Auto-attached dimension-grounded citation — passage "
                        "from the top retrieved chunk (not LLM-grounded)."
                    ),
                },
            ))
            real_kept += 1
        # A successful top-up supersedes the LLM's honest declines: showing
        # both "No supporting passage found" rows AND real citations would
        # contradict itself (mirrors _ensure_minimum_citations, which replaces
        # declines with the fallback when it succeeds).
        if real_kept > 0:
            kept = [c for c in kept if not c.no_citation]
        return kept

    def _build_chunk_label_map(
        self,
        retrieval: ModuleRetrievalResult,
    ) -> dict[str, str]:
        """Map prompt labels (DOC-1, NORM-2, PRAC-3) to real ChromaDB chunk ids."""
        label_map: dict[str, str] = {}
        for i, c in enumerate(retrieval.document_chunks, 1):
            cid = c.get("chunk_id")
            if cid:
                label_map[f"DOC-{i}"] = cid
        for i, c in enumerate(retrieval.module1_chunks, 1):
            cid = c.get("chunk_id")
            if cid:
                label_map[f"NORM-{i}"] = cid
        for i, c in enumerate(retrieval.module2_chunks, 1):
            cid = c.get("chunk_id")
            if cid:
                label_map[f"PRAC-{i}"] = cid
        return label_map

    def _translate_chunk_ids(
        self,
        citations: list[Any],
        label_map: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Resolve any label-style chunk_id to the real id before verification."""
        translated: list[dict[str, Any]] = []
        for c in citations:
            if isinstance(c, dict):
                entry = dict(c)
            else:
                entry = c.model_dump()
            cid = entry.get("chunk_id", "")
            if cid and cid in label_map:
                entry["chunk_id"] = label_map[cid]
            translated.append(entry)
        return translated

    def _build_evidence_list(
        self,
        citations: list[ModuleCitation],
        similarity_map: dict[str, float],
    ) -> list[RetrievedEvidence]:
        evidence_list: list[RetrievedEvidence] = []
        seen: set[str] = set()
        for cit in citations:
            if cit.chunk_id in seen or not cit.chunk_id:
                continue
            seen.add(cit.chunk_id)
            evidence_list.append(RetrievedEvidence(
                chunk_id=cit.chunk_id,
                text=cit.quote[:500],
                page_number=cit.page_number,
                source_framework=cit.source,
                document_name=getattr(cit, "document_name", None),
                similarity_score=similarity_map.get(cit.chunk_id),
                verified=cit.verified,
                verification=cit.verification,
            ))
        return evidence_list

    # ── Covered-tier synthesis completeness guard (deterministic) ───────

    @staticmethod
    def _build_covered_synthesis_fallback(
        dimension: str,
        module1_chunks: list[dict[str, Any]],
        coverage_example: str,
        operational_mechanisms: list[str],
    ) -> tuple[str, str, str]:
        """Deterministic fallback synthesis for a Covered dimension whose LLM
        synthesis came back empty — a Covered verdict must never ship without
        the 'Framework Synthesis — why this is compliant' comparison.

        Pure code (no LLM judgment): names the frameworks actually retrieved
        for this dimension (traceable), states the collective requirement in
        neutral terms, and grounds the compliance claim in the document's own
        provisions (the LLM's document-grounded coverage_example, or the
        operational mechanisms). Present tense only — no gap-filling
        language, so it can never trip the synthesis-drift guard.
        """
        fw_names: list[str] = []
        for c in module1_chunks or []:
            name = (c.get("source_framework") or "").strip()
            if name and name not in fw_names:
                fw_names.append(name)
        fw_label = (
            ", ".join(fw_names) if fw_names else "the international frameworks assessed"
        )

        consensus = (
            f"The frameworks assessed for this dimension ({fw_label}) "
            f"collectively require {dimension} to be governed in AI systems — "
            "clear allocation of responsibility, oversight of AI outcomes, and "
            "accountability for harms."
        )
        differences = (
            "They differ in emphasis: normative instruments frame this as a "
            "principle or rights obligation, while practical toolkits specify "
            "the concrete mechanisms (reporting, audits, redress) that give "
            "it effect."
        )
        provisions = (
            coverage_example.strip()
            or "; ".join(operational_mechanisms[:3]).strip()
            or "the document's stated commitments"
        )
        # Em-dash appositive framing keeps the sentence grammatical whether
        # provisions is one item or a semicolon-joined list (a singular
        # subject must not take a plural verb).
        overall = (
            f"The uploaded policy already satisfies this expectation: the "
            f"{dimension} principle is given operational effect in the "
            f"document — {provisions} — so the policy substantively meets "
            "the international requirement."
        )
        return consensus, differences, overall

    # ── Single combined per-dimension analysis ──────────────────────────

    def _analyze_dimension_combined(
        self,
        dimension: str,
        retrieval: ModuleRetrievalResult,
        debug_ctx: dict[str, Any] | None = None,
        country: str = "",
    ) -> GovernanceGap:
        dimension_def = analysis_prompts.build_dimension_definition_block(dimension)
        sys_prompt, prompt = analysis_prompts.build_module1_2_combined_prompt(
            dimension=dimension,
            dimension_definition=dimension_def,
            document_chunks=retrieval.document_chunks,
            module1_chunks=retrieval.module1_chunks,
            module2_chunks=retrieval.module2_chunks,
            country=country,
        )

        combined = generate_with_retry(
            provider=self.provider,
            prompt=prompt,
            schema=self._get_combined_module_schema(),
            system_prompt=sys_prompt,
            operation=f"module1_2_{dimension.lower().replace(' ', '_')}",
            debug_ctx=debug_ctx,
        )

        # ── Normalize Module 1 fields ───────────────────────────────────
        coverage_str = str(getattr(combined, "coverage", "Partial") or "Partial").strip().capitalize()
        if coverage_str not in ("Covered", "Partial", "Missing"):
            coverage_str = "Partial"
        coverage = CoverageLevel(coverage_str)

        reason_flagged = str(getattr(combined, "reason_flagged", "") or "")
        coverage_reasoning = str(getattr(combined, "coverage_reasoning", "") or "")
        coverage_example = str(getattr(combined, "coverage_example", "") or "")
        principle_ack = bool(getattr(combined, "principle_acknowledged", True))
        mechanisms = [m for m in (getattr(combined, "operational_mechanisms", []) or []) if m]

        # ── Deterministic coverage validation (ladder enforcement) ─────
        # The LLM's raw coverage label is graded against the document's own
        # acknowledged signals (operational mechanisms and
        # implementation-commitment language in the retrieved document
        # chunks). This reinstates the ladder rules the old Stage 1-4
        # plausibility validator provided but the merged single-call path
        # dropped: a document with an explicit commitment or attempted
        # mechanism is at least Partial (R1 floor, Level 1 → Partial; a bare
        # risk acknowledgment with no proposed action is NOT enough), and a
        # document with a concrete implementation commitment is Covered
        # (R2 raise, Level 3 → Covered — Partial verdicts only).
        raw_coverage = coverage
        validated_coverage, coverage_rules = validate_coverage_deterministic(
            coverage=coverage,
            principle_acknowledged=principle_ack,
            operational_mechanisms=mechanisms,
            document_chunks=retrieval.document_chunks,
            # Dimension grounding: R1/R2 only fire on chunks topically
            # related to this dimension, so a UN advisory-body participation
            # paragraph can never trigger Accountability (or an events
            # calendar trigger Inclusivity) on commitment vocabulary alone.
            dimension=dimension,
        )
        if coverage_rules:
            coverage = validated_coverage
            coverage_reasoning = (
                coverage_reasoning
                + (" " if coverage_reasoning else "")
                + "[Deterministic ladder check] " + " ".join(coverage_rules)
            )
            # A raised-to-Covered dimension is no longer a gap — its
            # reason_flagged (the model's "lacks X" text) would contradict
            # the Covered verdict and the Best Practices framing, so clear it.
            if coverage == CoverageLevel.COVERED:
                reason_flagged = (
                    "No critical gap — coverage raised by deterministic ladder "
                    "check (implementation commitment identified)."
                )
            logger.info(
                "coverage_deterministic_adjusted",
                dimension=dimension,
                raw_coverage=raw_coverage.value,
                validated_coverage=coverage.value,
                rules=coverage_rules,
            )

        # gap_detected follows the VALIDATED coverage, not the LLM's label
        # (a dimension deterministically raised to Covered has no gap).
        gap_detected = coverage != CoverageLevel.COVERED

        # ── Deterministic governance maturity (never free LLM judgment) ─
        maturity, maturity_reasoning = compute_governance_maturity(
            coverage=coverage.value,
            principle_acknowledged=principle_ack,
            operational_mechanisms=mechanisms,
        )

        # ── Module 2 fields (raw LLM output) ────────────────────────────
        # Note: the LLM's `priority` value is deliberately IGNORED — priority
        # is deterministic code (resolve_priority) enforced by coverage tier.
        llm_recommendations = [r for r in (getattr(combined, "recommendations", []) or []) if r]
        intl_ref = str(getattr(combined, "international_standard_reference", "") or "")
        # Structured framework synthesis (Consensus / Differences / Overall
        # assessment). A legacy plain-string value is tolerated (treated as the
        # overall assessment) but the structured fields are authoritative.
        raw_fs = getattr(combined, "framework_synthesis", None)
        fs_consensus = ""
        fs_differences = ""
        fs_overall = ""
        # The LLM schema declares framework_synthesis as a nested
        # FrameworkSynthesisSchema, so generate_with_retry returns a Pydantic
        # model instance — NOT a plain dict. Normalize to a dict before
        # reading the three parts (a legacy plain-string value is tolerated
        # and treated as the overall assessment).
        if hasattr(raw_fs, "model_dump"):
            raw_fs_dict = raw_fs.model_dump()
        elif isinstance(raw_fs, dict):
            raw_fs_dict = raw_fs
        else:
            raw_fs_dict = None
        if isinstance(raw_fs_dict, dict):
            fs_consensus = str(raw_fs_dict.get("consensus", "") or "")
            fs_differences = str(raw_fs_dict.get("differences", "") or "")
            fs_overall = str(raw_fs_dict.get("overall_assessment", "") or "")
        elif raw_fs is not None:
            fs_overall = str(raw_fs)
        # Composed legacy string — keeps every existing consumer (consistency
        # drift check, advisor, executive summary) working unchanged.
        framework_synthesis = "\n\n".join(
            p for p in [
                f"Consensus: {fs_consensus}" if fs_consensus else "",
                f"Differences: {fs_differences}" if fs_differences else "",
                f"Overall assessment: {fs_overall}" if fs_overall else "",
            ] if p
        )
        future_strengthening_opportunities = [
            e for e in (getattr(combined, "future_strengthening_opportunities", []) or []) if e
        ]
        raw_international_examples = getattr(combined, "international_examples", []) or []

        # Defensive: the prompt shows real chunk_ids, but if the model echoes
        # a label (DOC-1 / NORM-2 / PRAC-3), translate it back to the real id.
        # Built up front so EVERY citation path (including international
        # examples) shares the same label→id translation.
        label_to_id = self._build_chunk_label_map(retrieval)

        # ── Coverage-tier enforcement (code, never LLM judgment) ────────
        # Fully Covered: Best Practices replaces Recommendations/Priority.
        # Priority is omitted (null); recommendations are emptied even if the
        # model produced them. International examples are anti-fabrication
        # filtered: any example whose chunk cannot be resolved to a real,
        # existing vector-store chunk is dropped.
        if coverage == CoverageLevel.COVERED:
            recommendations: list[str] = []
            priority: Priority | None = None
            best_practices = BestPractices(
                opening=BEST_PRACTICES_OPENING,
                future_strengthening_opportunities=future_strengthening_opportunities[:3],
                international_examples=self._verify_international_examples(
                    raw_international_examples,
                    label_map=label_to_id,
                ),
            )
        else:
            recommendations = llm_recommendations
            # Deterministic priority: Partial→Medium / Missing→High, with
            # compounding escalation applied later once all dimensions are known.
            priority = resolve_priority(coverage, dimension)
            best_practices = None

        # ── Fully Covered synthesis-drift safeguard (deterministic) ────
        # A Covered verdict whose own framework_synthesis reads as a
        # recommendation / gap-fill ("should establish", "would strengthen",
        # "recommend", "lacks"...) has drifted from its tier. Strong signals
        # auto-downgrade to Partial for review instead of shipping a
        # self-contradictory report section. Weak signals are logged and
        # reported by the consistency validator as flags.
        synthesis_drift_downgraded = False
        # Drift detection scans ONLY the overall_assessment part of a Covered
        # synthesis (the compliance justification) — the Consensus / Differences
        # sections describe the external frameworks, where words like "lacks"
        # or "requires" legitimately describe framework positions, not the
        # policy. Gap-filling language in the overall assessment is the true
        # tier/content drift signal.
        drift_text = fs_overall or framework_synthesis
        if coverage == CoverageLevel.COVERED and drift_text:
            drift_score, drift_phrases = detect_covered_synthesis_drift(drift_text)
            if drift_score >= COVERED_SYNTHESIS_DOWNGRADE_THRESHOLD:
                logger.warning(
                    "covered_synthesis_drift_downgraded",
                    dimension=dimension,
                    drift_score=drift_score,
                    drift_phrases=drift_phrases,
                )
                coverage = CoverageLevel.PARTIAL
                gap_detected = True
                synthesis_drift_downgraded = True
                reason_flagged = (
                    "Auto-downgraded from Covered for review: framework synthesis "
                    "used gap-filling/recommendation language "
                    f"({', '.join(drift_phrases[:5])}) inconsistent with a Covered "
                    "verdict."
                )
                coverage_reasoning = (
                    (coverage_reasoning + " " if coverage_reasoning else "")
                    + f"[Synthesis-drift review] Covered downgraded to Partial: "
                    f"framework synthesis used '{', '.join(drift_phrases[:5])}'."
                )
                # Re-run the Partial tier: real recommendations + Medium priority.
                recommendations = llm_recommendations
                priority = resolve_priority(coverage, dimension)
                best_practices = None
                # Recompute maturity under the corrected coverage.
                maturity, maturity_reasoning = compute_governance_maturity(
                    coverage=coverage.value,
                    principle_acknowledged=principle_ack,
                    operational_mechanisms=mechanisms,
                )
            elif drift_score > 0:
                logger.warning(
                    "covered_synthesis_drift_flagged",
                    dimension=dimension,
                    drift_score=drift_score,
                    drift_phrases=drift_phrases,
                )

        # ── Covered-tier synthesis completeness guard (deterministic) ───
        # A Covered verdict must never ship without the 'why this is
        # compliant' framework comparison. The overall_assessment is the
        # compliance justification — the part that explains how the policy
        # ALREADY satisfies the international expectation. If the model left
        # it empty (occasional on some dimensions), fill the missing part(s)
        # deterministically from the retrieved normative frameworks + the
        # document's own provisions, so the frontend's "Framework Synthesis —
        # why this is compliant" block always has content for the Covered
        # tier. Real consensus/differences the model produced are preserved.
        # Runs AFTER the drift check so it only fires when the final coverage
        # really is Covered.
        if coverage == CoverageLevel.COVERED and not fs_overall:
            fb_consensus, fb_differences, fb_overall = (
                self._build_covered_synthesis_fallback(
                    dimension=dimension,
                    module1_chunks=retrieval.module1_chunks,
                    coverage_example=coverage_example,
                    operational_mechanisms=mechanisms,
                )
            )
            was_consensus_empty = not fs_consensus
            was_differences_empty = not fs_differences
            if was_consensus_empty:
                fs_consensus = fb_consensus
            if was_differences_empty:
                fs_differences = fb_differences
            fs_overall = fb_overall
            framework_synthesis = "\n\n".join(
                p for p in [
                    f"Consensus: {fs_consensus}" if fs_consensus else "",
                    f"Differences: {fs_differences}" if fs_differences else "",
                    f"Overall assessment: {fs_overall}" if fs_overall else "",
                ] if p
            )
            logger.info(
                "covered_synthesis_fallback_generated",
                dimension=dimension,
                filled_consensus=was_consensus_empty,
                filled_differences=was_differences_empty,
                filled_overall=True,
            )

        # ── Citation verification (both fields) ─────────────────────────
        doc_citations = self._verify_module_citations(
            self._translate_chunk_ids(getattr(combined, "document_evidence", []) or [], label_to_id),
            default_source="Uploaded Document",
            source_type="document",
        )
        fw_citations = self._verify_module_citations(
            self._translate_chunk_ids(getattr(combined, "framework_evidence", []) or [], label_to_id),
            source_type="framework",
        )
        std_citations = self._verify_module_citations(
            self._translate_chunk_ids(getattr(combined, "standard_citations", []) or [], label_to_id),
            source_type="framework",
        )

        # Missing / Partial findings must still carry a framework requirement
        # citation (spec), but the deterministic fallback must NEVER attach an
        # off-topic or un-sourced chunk: the fallback chunk must be
        # dimension-grounded (shared ladder check) and carry a real framework
        # name — "Source: Unknown" must never reach a user.
        if coverage != CoverageLevel.COVERED:
            fw_citations = self._ensure_minimum_citations(
                fw_citations,
                retrieval.module1_chunks,
                claim_note="Normative requirement establishing this governance dimension",
                source_type="framework",
                dimension=dimension,
            )
        # NOTE: document evidence is NEVER auto-attached. The LLM's own
        # document citations (verified or unverified) are the only document
        # evidence shown; when the model declines to cite, the section shows
        # the honest "no specific document evidence found" state instead of a
        # top retrieved chunk the model did not ground.

        module1 = Module1Evaluation(
            dimension=dimension,
            coverage=coverage,
            gap_detected=gap_detected,
            reason_flagged=reason_flagged,
            coverage_reasoning=coverage_reasoning,
            coverage_example=coverage_example,
            principle_acknowledged=principle_ack,
            operational_mechanisms=mechanisms,
            governance_maturity=maturity,
            maturity_reasoning=maturity_reasoning,
            document_evidence=doc_citations,
            framework_evidence=fw_citations,
        )
        module2 = Module2Recommendation(
            dimension=dimension,
            recommendations=recommendations,
            priority=priority,
            international_standard_reference=intl_ref,
            framework_synthesis=framework_synthesis,
            framework_synthesis_consensus=fs_consensus,
            framework_synthesis_differences=fs_differences,
            framework_synthesis_overall_assessment=fs_overall,
            standard_citations=std_citations,
            best_practices=best_practices,
        )

        # ── Legacy fields + confidence + risk ───────────────────────────
        similarity_map = {
            c.get("chunk_id"): c.get("similarity_score")
            for c in retrieval.all_chunks_labeled()
            if c.get("chunk_id")
        }
        evidence_list = self._build_evidence_list(
            doc_citations + fw_citations + std_citations, similarity_map
        )
        conf_score, conf_method = compute_calibrated_confidence(
            evidence_list=evidence_list,
            coverage_level=coverage,
            dimension=dimension,
        )
        risk, risk_reason = compute_risk(coverage, dimension)

        gap = GovernanceGap(
            dimension=dimension,
            coverage=coverage,
            gap_found=gap_detected,
            evidence=evidence_list,
            reason_flagged=reason_flagged,
            recommendation="\n".join(recommendations) if recommendations else "",
            risk_level=risk,
            risk_reason=risk_reason,
            un_recommendation=recommendations[0] if recommendations else "",
            framework_synthesis=framework_synthesis,
            confidence_score=conf_score,
            confidence_method=conf_method,
            coverage_reasoning=coverage_reasoning,
            gap_analysis="\n\n".join(
                p for p in [
                    f"Coverage: {coverage.value}",
                    f"Reason flagged: {reason_flagged}" if reason_flagged else "",
                    f"Governance Maturity: {maturity.value}",
                    coverage_reasoning,
                    (f"Coverage examples: {coverage_example}" if coverage_example else ""),
                    (f"Best practices:\n{best_practices.opening}" if best_practices else ""),
                    (f"Future strengthening opportunities:\n" + "\n".join(f"- {e}" for e in best_practices.future_strengthening_opportunities) if best_practices and best_practices.future_strengthening_opportunities else ""),
                    (f"Recommendations ({priority.value} priority):\n" + "\n".join(
                        f"- {r}" for r in recommendations
                    ) if recommendations and priority else ""),
                    f"Framework synthesis: {framework_synthesis}" if framework_synthesis else "",
                ] if p
            ),
            governance_maturity=maturity,
            maturity_reasoning=maturity_reasoning,
            module_1=module1,
            module_2=module2,
            synthesis_drift_downgraded=synthesis_drift_downgraded,
        )

        module2_json = module2.model_dump_json()
        logger.info(
            "module_1_2_analysis_complete",
            dimension=dimension,
            coverage=coverage.value,
            governance_maturity=maturity.value,
            priority=priority.value if priority else None,
            tier="best_practices" if coverage == CoverageLevel.COVERED else "recommendations",
            module2_output_chars=len(module2_json),
            num_doc_citations=len(doc_citations),
            num_fw_citations=len(fw_citations),
            num_std_citations=len(std_citations),
            num_future_strengthening_opportunities=len(future_strengthening_opportunities),
            num_international_examples=len(best_practices.international_examples) if best_practices else 0,
            synthesis_drift_downgraded=synthesis_drift_downgraded,
            verified=sum(1 for c in doc_citations + fw_citations + std_citations if c.verified),
            total=len(doc_citations) + len(fw_citations) + len(std_citations),
        )
        return gap

    # ── Module 3 + Module 4 — conditional second call ───────────────────

    @staticmethod
    def _get_module34_schema() -> type[BaseModel]:
        class PhaseSchema(BaseModel):
            phase: str
            timeline: str = ""
            objective: str = ""
            steps: list[str] = []

        class CitationSchema(BaseModel):
            chunk_id: str
            quote: str
            page_number: int | None = None

        class IncidentSchema(BaseModel):
            incident_name: str
            source: str = ""
            dimension_relevance: str = ""
            potential_consequence: str = ""
            lessons_learned: str = ""
            mitigation: str = ""
            chunk_id: str = ""
            quote: str = ""
            page_number: int | None = None

        class Module34Schema(BaseModel):
            dimension: str
            # Module 3 — Implementation Roadmap
            phases: list[PhaseSchema]
            responsible_agency: str
            responsible_agency_grounding: str = "none_identified"
            documentation_requirements: list[str] = []
            monitoring_checklist: list[str] = []
            implementation_citations: list[CitationSchema] = []
            # Module 4 — Case Intelligence
            incident_matches: list[IncidentSchema] = []
            matched: bool = False

        return Module34Schema

    @staticmethod
    def _build_dimension_verdict_text(gap: GovernanceGap) -> str:
        """Carry-forward the Module 1+2 verdict as compact text context for the
        Module 3+4 call, so it addresses the ACTUAL gap instead of re-deriving
        it. Kept as text (not re-retrieved chunks) to stay within the context
        budget — the Module 3+4 call must not balloon."""
        m1 = gap.module_1
        m2 = gap.module_2
        lines = [
            f"Dimension: {gap.dimension}",
            f"Coverage: {gap.coverage.value}",
        ]
        if gap.coverage_reasoning:
            lines.append(f"Coverage reasoning: {gap.coverage_reasoning}")
        if m1 and m1.reason_flagged:
            lines.append(f"Reason flagged: {m1.reason_flagged}")
        if m1 and m1.operational_mechanisms:
            lines.append(f"Existing operational mechanisms in document: {'; '.join(m1.operational_mechanisms[:6])}")
        if gap.governance_maturity:
            lines.append(f"Governance maturity: {gap.governance_maturity.value}")
        if m2 and m2.recommendations:
            lines.append("Module 2 recommendations (the gap this roadmap must address):")
            lines.extend(f"  - {r}" for r in m2.recommendations[:5])
        return "\n".join(lines)

    @staticmethod
    def _verify_responsible_agency(
        responsible_agency: str,
        grounding: str,
        document_chunks: list[dict[str, Any]],
        dimension: str,
    ) -> tuple[str, str]:
        """Deterministic responsible-agency anti-fabrication gate.

        The LLM may claim 'document_named' but invent an agency that is not in
        the document (the highest-fabrication-risk field in Module 3). This
        code re-grounds the claim against the actual document chunks:
          - document_named: the agency name must appear (whole-word) in a
            dimension-topical document chunk AND match a named-body keyword.
          - document_implied: at least one dimension-topical document chunk
            must exist (something in the doc implies an institutional owner).
          - none_identified: stays as the explicit honest state; the name must
            contain the 'Not specified by policy' phrasing.
        Any claim that fails its bar is downgraded to the honest state rather
        than shipping a plausible-sounding fabricated agency.
        """
        chunk_texts = [(c.get("text") or "") for c in (document_chunks or [])]
        topical = [t for t in chunk_texts if _chunk_matches_dimension(t, dimension)]

        grounding_norm = (grounding or "").strip().lower()
        name = (responsible_agency or "").strip()

        if grounding_norm in ("document_named", "document_implied"):
            # The agency must be findable in the document's own text.
            if not name or not topical:
                return (
                    "Not specified by policy — implementation responsibility "
                    "should be assigned by the adopting government.",
                    "none_identified",
                )
            name_lower = name.lower()
            found = False
            for t in topical:
                t_lower = t.lower()
                if name_lower in t_lower and _has_keyword(t, NAMED_BODY_KEYWORDS):
                    found = True
                    break
            if not found:
                # document_implied: the document implies an institutional
                # owner without naming it. The anti-fabrication bar still
                # applies — the name must be a generic role/institution type
                # (ministry/council/office/authority/board...), never a
                # specific invented agency. Requiring a named-body keyword in
                # the NAME itself is what stops the LLM claiming "implied"
                # for a plausible-sounding fabricated institution.
                if grounding_norm == "document_implied" and _has_keyword(name, NAMED_BODY_KEYWORDS):
                    return name, "document_implied"
                return (
                    "Not specified by policy — implementation responsibility "
                    "should be assigned by the adopting government.",
                    "none_identified",
                )
            return name, grounding_norm

        # none_identified — enforce the explicit honest phrasing. The model
        # must write the "Not specified by policy" state verbatim — no
        # plausible-sounding invented agency is ever accepted.
        if "not specified by policy" not in name.lower():
            return (
                "Not specified by policy — implementation responsibility "
                "should be assigned by the adopting government.",
                "none_identified",
            )
        return name, "none_identified"

    def _workspace_document_text(self, workspace_id: str) -> str:
        """All uploaded-document chunk text for a workspace (for verbatim
        name-verification in the Module 2 agency cross-reference)."""
        try:
            res = self.vector_store.collection.get(
                where={"workspace_id": workspace_id},
                include=["documents"],
            )
        except Exception:
            return ""
        return " \n".join(res.get("documents", []) or [])

    def _reconcile_responsible_agency_with_module2(
        self,
        agency: str,
        grounding: str,
        recommendations: list[str],
        workspace_id: str = "",
    ) -> tuple[str, str]:
        """Close the Module 2 / Module 3 responsible-agency contradiction.

        Module 2's recommendations can name specific institutions (e.g.
        "MeitY", "Bureau of Indian Standards") for the same dimension where
        Module 3's anti-fabrication gate correctly returns "Not specified by
        policy" — the policy names the bodies but never assigns THIS
        responsibility in a dimension-topical context. Both statements are
        true, but they read as contradictory. When the gate yields
        none_identified, append a deterministic cross-reference naming the
        document-grounded institutions Module 2 recommended, so the two
        sections read consistently without inventing an assignment the policy
        never made. Names are verified verbatim against the full uploaded
        document before they are mentioned; if none can be verified, the
        honest verdict is returned unchanged.
        """
        if grounding != "none_identified" or not recommendations:
            return agency, grounding
        if not workspace_id:
            return agency, grounding
        doc_text = self._workspace_document_text(workspace_id)
        if not doc_text:
            return agency, grounding
        names = _extract_document_grounded_institutions(recommendations, doc_text)
        if not names:
            return agency, grounding
        joined = names[0] if len(names) == 1 else f"{names[0]} and {names[1]}"
        plural = "these bodies" if len(names) > 1 else "this body"
        note = (
            f"{agency} Module 2 recommends tasking {joined}; the policy "
            f"names {plural} but does not assign it this responsibility."
        )
        return note, grounding

    def _analyze_module34_combined(
        self,
        dimension: str,
        gap: GovernanceGap,
        retrieval: Module34RetrievalResult,
        debug_ctx: dict[str, Any] | None = None,
        country: str = "",
        workspace_id: str = "",
    ) -> None:
        """Conditional Module 3 + Module 4 combined call for Partial/Missing.

        Runs ONLY when coverage is Partial or Missing (code gate in analyze()).
        Mutates `gap` in place: sets gap.module_3 always, and gap.module_4 only
        when a genuinely relevant, dimension-grounded incident match exists.
        """
        dimension_def = analysis_prompts.build_dimension_definition_block(dimension)
        verdict_text = self._build_dimension_verdict_text(gap)
        sys_prompt, prompt = analysis_prompts.build_module3_4_combined_prompt(
            dimension=dimension,
            dimension_definition=dimension_def,
            dimension_verdict=verdict_text,
            module3_chunks=retrieval.module3_chunks,
            module4_chunks=retrieval.module4_chunks,
            document_chunks=retrieval.document_chunks,
            country=country,
        )

        combined = generate_with_retry(
            provider=self.provider,
            prompt=prompt,
            schema=self._get_module34_schema(),
            system_prompt=sys_prompt,
            operation=f"module3_4_{dimension.lower().replace(' ', '_')}",
            debug_ctx=debug_ctx,
        )

        # ── Label map: IMPL-n / INC-n / DOC-n → real chunk ids ────────
        label_to_id: dict[str, str] = {}
        for i, c in enumerate(retrieval.module3_chunks, 1):
            cid = c.get("chunk_id")
            if cid:
                label_to_id[f"IMPL-{i}"] = cid
        for i, c in enumerate(retrieval.module4_chunks, 1):
            cid = c.get("chunk_id")
            if cid:
                label_to_id[f"INC-{i}"] = cid
        for i, c in enumerate(retrieval.document_chunks, 1):
            cid = c.get("chunk_id")
            if cid:
                label_to_id[f"DOC-{i}"] = cid

        # ── Module 3 — Implementation Roadmap ─────────────────────────
        # The responsible-agency gate may downgrade to "Not specified by
        # policy" (the policy never assigns this duty in a dimension-topical
        # context). Module 2's recommendations for the SAME dimension can then
        # name document-grounded institutions (e.g. MeitY, a standards body) —
        # both true, but they read as contradictory. Reconcile deterministically:
        # keep the honest verdict and append a cross-reference to the bodies
        # Module 2 recommended (verified verbatim against the document).
        phases_raw = getattr(combined, "phases", []) or []
        phases: list[Module3Phase] = []
        for ph in phases_raw[:2]:
            if isinstance(ph, dict):
                steps = [s for s in (ph.get("steps") or []) if s][:5]
                phases.append(Module3Phase(
                    phase=str(ph.get("phase", "") or ""),
                    timeline=str(ph.get("timeline", "") or ""),
                    objective=str(ph.get("objective", "") or ""),
                    steps=steps,
                ))
            else:
                steps = [s for s in (getattr(ph, "steps", []) or []) if s][:5]
                phases.append(Module3Phase(
                    phase=str(getattr(ph, "phase", "") or ""),
                    timeline=str(getattr(ph, "timeline", "") or ""),
                    objective=str(getattr(ph, "objective", "") or ""),
                    steps=steps,
                ))

        raw_agency = str(getattr(combined, "responsible_agency", "") or "")
        raw_grounding = str(getattr(combined, "responsible_agency_grounding", "") or "")
        agency, grounding = self._verify_responsible_agency(
            raw_agency, raw_grounding, retrieval.document_chunks, dimension,
        )
        agency, grounding = self._reconcile_responsible_agency_with_module2(
            agency,
            grounding,
            (gap.module_2.recommendations if gap.module_2 else []) or [],
            workspace_id=workspace_id,
        )

        # ── Deterministic implementation timelines (never LLM guesswork) ──
        # The LLM's `timeline` output is IGNORED — the model was told to pick
        # a "realistic range" and echoed the prompt's example values
        # ("0-12 months") with no basis in the document. The range is now
        # computed in code from signals the pipeline already derived
        # deterministically (coverage tier, existing operational mechanisms,
        # governance maturity, responsible-agency grounding, phase scope),
        # with an explicit reasoning string so the estimate is auditable.
        step_counts = [len(p.steps) for p in phases]
        timelines = estimate_phase_timelines(
            coverage=gap.coverage,
            operational_mechanisms=(
                gap.module_1.operational_mechanisms if gap.module_1 else []
            ),
            maturity=gap.governance_maturity,
            agency_grounding=grounding,
            step_counts=step_counts,
        )
        for i, phase in enumerate(phases):
            if i < len(timelines):
                phase.timeline = timelines[i]["timeline"]
                phase.timeline_reasoning = timelines[i]["reasoning"]
        logger.info(
            "module3_timelines_estimated",
            dimension=dimension,
            coverage=gap.coverage.value,
            agency_grounding=grounding,
            timelines=[t["timeline"] for t in timelines],
        )

        documentation = [d for d in (getattr(combined, "documentation_requirements", []) or []) if d]
        monitoring = [m for m in (getattr(combined, "monitoring_checklist", []) or []) if m]

        # Module 3 citations — same verification path as Module 1+2, then the
        # dimension-grounding gate (same discipline as Module 4 matching): an
        # LLM citation whose chunk is NOT topically about this dimension is
        # dropped (verified-but-irrelevant is worse than honest absence) and
        # the slots are re-filled deterministically from the best
        # dimension-topical chunks in the retrieved implementation-source and
        # uploaded-document buckets.
        impl_citations_raw = self._translate_chunk_ids(
            getattr(combined, "implementation_citations", []) or [], label_to_id,
        )
        impl_citations = self._verify_module_citations(
            impl_citations_raw,
            source_type="framework",
        )
        impl_citations = self._ground_module3_citations(
            impl_citations,
            list(retrieval.document_chunks) + list(retrieval.module3_chunks),
            dimension,
            phases_count=len(phases),
        )

        gap.module_3 = Module3Implementation(
            dimension=dimension,
            coverage_tier=gap.coverage.value,
            phases=phases,
            responsible_agency=agency,
            responsible_agency_grounding=grounding,
            documentation_requirements=documentation,
            monitoring_checklist=monitoring,
            citations=impl_citations,
        )

        # ── Module 4 — Case Intelligence (dimension-grounded matching) ─
        # The matching step is retrieval-only + grounded: each incident the
        # model references must resolve to a REAL module_4_incident chunk that
        # ALSO passes the shared dimension-grounding check (the same
        # _chunk_matches_dimension used by Module 1+2's ladder). A loosely-
        # related incident that ranks on raw similarity but is not topically
        # about this dimension is dropped, never force-included. Only the
        # write-up fields come from the LLM, around the grounded incident.
        incidents_raw = getattr(combined, "incident_matches", []) or []
        grounded_incidents: list[IncidentMatch] = []
        for inc in incidents_raw:
            if isinstance(inc, dict):
                chunk_id = inc.get("chunk_id", "") or ""
                quote = inc.get("quote", "") or ""
                page = inc.get("page_number")
                name = inc.get("incident_name", "") or ""
                src = inc.get("source", "") or ""
                rel = inc.get("dimension_relevance", "") or ""
                cons = inc.get("potential_consequence", "") or ""
                less = inc.get("lessons_learned", "") or ""
                mitig = inc.get("mitigation", "") or ""
            else:
                chunk_id = getattr(inc, "chunk_id", "") or ""
                quote = getattr(inc, "quote", "") or ""
                page = getattr(inc, "page_number", None)
                name = getattr(inc, "incident_name", "") or ""
                src = getattr(inc, "source", "") or ""
                rel = getattr(inc, "dimension_relevance", "") or ""
                cons = getattr(inc, "potential_consequence", "") or ""
                less = getattr(inc, "lessons_learned", "") or ""
                mitig = getattr(inc, "mitigation", "") or ""

            if self._is_no_citation_entry(chunk_id, quote) or not chunk_id:
                continue
            real_id = label_to_id.get(chunk_id, chunk_id)
            chunk = self.vector_store.get_chunk(real_id)
            if chunk is None:
                continue
            md = chunk.get("metadata", {}) or {}
            roles = str(md.get("roles", "") or "")
            if "module_4_incident" not in roles:
                continue
            chunk_text = chunk.get("text", "") or ""
            # Dimension grounding — the shared check. An off-topic incident
            # (e.g. an AI-security incident for an Inclusivity gap) never
            # matches on vocabulary alone.
            if not _chunk_matches_dimension(chunk_text, dimension):
                continue

            citation = self._verify_module_citations(
                [{"chunk_id": real_id, "quote": quote, "page_number": page}],
                default_source=src or md.get("framework", "") or "",
                source_type="framework",
            )[0]
            grounded_incidents.append(IncidentMatch(
                incident_name=name,
                source=src or md.get("framework", "") or "",
                dimension_relevance=rel,
                potential_consequence=cons,
                lessons_learned=less,
                mitigation=mitig,
                citation=citation,
            ))

        matched = bool(grounded_incidents)
        if matched:
            gap.module_4 = Module4CaseIntelligence(
                dimension=dimension,
                matched=True,
                incident_matches=grounded_incidents,
                summary=(
                    f"{len(grounded_incidents)} curated incident record(s) matched "
                    f"this {dimension} gap."
                ),
            )
        else:
            gap.module_4 = Module4CaseIntelligence(
                dimension=dimension,
                matched=False,
                incident_matches=[],
                summary="No genuinely relevant curated incident found for this dimension — "
                         "Module 4 omitted rather than force-matching a weak case.",
            )

        module34_json = combined.model_dump_json()
        logger.info(
            "module_3_4_analysis_complete",
            dimension=dimension,
            coverage_tier=gap.coverage.value,
            module34_output_chars=len(module34_json),
            num_phases=len(phases),
            responsible_agency_grounding=grounding,
            num_impl_citations=len(impl_citations),
            num_incidents_generated=len(incidents_raw),
            num_incidents_grounded=len(grounded_incidents),
            module4_matched=matched,
            verified=sum(1 for c in impl_citations if c.verified),
            total=len(impl_citations),
        )

    # ── Orchestration ───────────────────────────────────────────────────

    def _emit_dimension(
        self,
        state: _DimensionRunState,
        dimension: str,
        gap: GovernanceGap,
        provider_info: dict[str, Any],
    ) -> None:
        """Fire the dimension callback from a worker thread.

        The callback itself is tiny (tasks.py appends to a list, atomic
        under the GIL) and is guarded so a callback exception can never
        corrupt the gap result in-flight.
        """
        if state.callback is not None:
            try:
                state.callback(dimension, gap, provider_info)
            except Exception:
                pass

    def _analyze_one_dimension(
        self,
        dimension: str,
        workspace_id: str,
        num_frameworks: int,
        country: str | None,
        state: _DimensionRunState,
    ) -> GovernanceGap:
        """Run the full per-dimension pipeline (deterministic routing →
        retrieval → Module 1+2 verdict → conditional Module 3+4) inside one
        worker of the bounded-parallel dimension loop.

        Never raises: any failure becomes an explicit error gap (never a
        fabricated finding), exactly as the sequential loop did. Shared
        counters are updated under state.lock.
        """
        try:
            # Deterministic framework routing (backend-only, no LLM):
            # core frameworks always + dimension-specific + regional.
            routed_frameworks = resolve_frameworks(dimension, country=country)
            logger.info(
                "dimension_frameworks_routed",
                dimension=dimension,
                country=country,
                frameworks=routed_frameworks,
            )
            retrieval = self.retrieval_pipeline.retrieve_module_chunks(
                dimension=dimension,
                workspace_id=workspace_id,
                # NOTE: deliberately NO user_query. The pipeline has no
                # user question, and passing document_name here injected
                # the UUID-prefixed upload filename (e.g.
                # "7355429b-..._niti_aayog_ai.pdf") into the embedding
                # query, which corrupted doc-bucket ranking — the
                # Transparency run retrieved a generic GDPR chunk instead
                # of the document's own "Transparency / opening the Black
                # Box" section, so the LLM honestly reported Missing. The
                # bare dimension name is the correct query; the document
                # bucket is already workspace-filtered.
                module1_frameworks=routed_frameworks,
                # Regional reserve: the country's region-routed subset
                # (e.g. Singapore Model AI Governance Framework for ASEAN)
                # gets guaranteed Module 1 budget so it cannot be crowded
                # out by the always-on core frameworks.
                module1_regional_frameworks=resolve_regional_frameworks(
                    country=country
                ),
                # Dimension reserve (Module 2): dimension-tagged practical
                # tools keep a guaranteed Module 2 budget slot for their
                # dimension (same rationale as the regional reserve).
                module2_dimension_frameworks=resolve_dimension_frameworks(
                    dimension, roles=["module_2_practical"]
                ),
            )
            with state.lock:
                state.doc_chunks_per_dimension[dimension] = len(
                    retrieval.document_chunks
                )
                state.all_retrieved.extend(retrieval.all_chunks_labeled())

            # No context at all → don't waste an LLM call or invite fabrication.
            if retrieval.total_chunks == 0:
                logger.warning(
                    "dimension_skipped_no_chunks",
                    dimension=dimension,
                    workspace_id=workspace_id,
                    reason="No module/document chunks retrieved for dimension.",
                )
                gap = self._build_insufficient_gap(dimension)
                self._emit_dimension(state, dimension, gap, {
                    "provider": self.provider.model_name,
                    "tier": self.provider.tier,
                    "error": "No chunks retrieved for dimension.",
                })
                return gap

            dim_start = time.time()
            gap = self._analyze_dimension_combined(
                dimension=dimension,
                retrieval=retrieval,
                debug_ctx={
                    "num_chunks": retrieval.total_chunks,
                    "num_frameworks": num_frameworks,
                },
                country=country,
            )
            with state.lock:
                state.llm_call_count += 1
                state.total_llm_latency += time.time() - dim_start

            # ── Conditional Module 3 + Module 4 second call ────────
            # Cost-control gate in code: only Partial/Missing dimensions
            # run this call (one combined call — never split). Fully
            # Covered dimensions are DONE after the Module 1+2 call;
            # their module_3/module_4 stay None (schema-null, not filler).
            if gap.coverage in (CoverageLevel.PARTIAL, CoverageLevel.MISSING):
                try:
                    m34_retrieval = self.retrieval_pipeline.retrieve_module34_chunks(
                        dimension=dimension,
                        workspace_id=workspace_id,
                        # Dimension reserve (Module 3): dimension-tagged
                        # implementation sources keep a guaranteed Module 3
                        # budget slot for their dimension.
                        module3_dimension_frameworks=resolve_dimension_frameworks(
                            dimension, roles=["module_3_implementation"]
                        ),
                    )
                    m34_start = time.time()
                    self._analyze_module34_combined(
                        dimension=dimension,
                        gap=gap,
                        retrieval=m34_retrieval,
                        debug_ctx={"num_chunks": m34_retrieval.total_chunks},
                        country=country,
                        workspace_id=workspace_id,
                    )
                    with state.lock:
                        state.llm_call_count += 1
                        state.total_llm_latency += time.time() - m34_start
                except Exception as exc:
                    # A Module 3+4 failure must NOT degrade the Module 1+2
                    # verdict — the dimension result stays valid; the
                    # roadmap/case sections are simply absent this run.
                    logger.warning(
                        "module_3_4_analysis_failed",
                        dimension=dimension,
                        error=str(exc),
                    )

            self._emit_dimension(state, dimension, gap, {
                "provider": self.provider.model_name,
                "tier": self.provider.tier,
            })
            return gap
        except Exception as exc:
            logger.error(
                "dimension_analysis_failed",
                dimension=dimension,
                error=str(exc),
            )
            # An LLM/provider failure is NOT a finding. Mark it explicitly
            # so it can never masquerade as "Insufficient Evidence" (a
            # genuine no-evidence verdict). The frontend shows a distinct
            # "Analysis failed" state; the summary counts it separately.
            error_gap = self._build_error_gap(dimension, str(exc))
            self._emit_dimension(state, dimension, error_gap, {
                "provider": self.provider.model_name,
                "tier": self.provider.tier,
                "error": str(exc),
            })
            return error_gap

    def analyze(
        self,
        document_text: str,
        document_name: str,
        workspace_id: str,
        frameworks: list[str] | None = None,
        existing_results: dict[str, GovernanceGap] | None = None,
        dimension_callback: Callable | None = None,
        country: str | None = None,
    ) -> GapAnalysisResult:
        start_time = time.time()
        analysis_id = str(uuid.uuid4())

        # Frameworks are routed deterministically per dimension/region inside
        # the loop (resolve_frameworks); the workspace-level list is only used
        # for the report's "Frameworks used" line. Empty (picker removed from
        # the UI) or None means "the full indexed reference library" — the
        # same pool the router draws from.
        if not frameworks:
            frameworks = self.vector_store.get_all_frameworks()

        num_frameworks = len(frameworks) if frameworks else 0

        existing_results = existing_results or {}

        # ── Bounded-parallel dimension loop ────────────────────────────
        # Dimensions used to run strictly sequentially (8 + up to 8 = up to
        # 16 LLM calls back to back). Now they run concurrently in a small
        # worker pool (ANALYSIS_MAX_CONCURRENCY, default 3 in flight), paced
        # underneath by the shared RPM throttle + jittered backoff in
        # provider_router — the free-tier request rate is never exceeded,
        # only wall-clock time improves. Results are re-assembled in
        # GOVERNANCE_DIMENSIONS order, so ordering, risk/priority
        # computation, and the report are identical to a sequential run.
        state = _DimensionRunState(dimension_callback)
        dimension_results: dict[str, GovernanceGap] = {}
        pending: list[str] = []
        for dimension in GOVERNANCE_DIMENSIONS:
            if dimension in existing_results:
                dimension_results[dimension] = existing_results[dimension]
            else:
                pending.append(dimension)

        if pending:
            max_workers = max(1, ANALYSIS_MAX_CONCURRENCY)
            if max_workers > 1 and len(pending) > 1:
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {
                        pool.submit(
                            self._analyze_one_dimension,
                            d, workspace_id, num_frameworks, country, state,
                        ): d
                        for d in pending
                    }
                    for fut in as_completed(futures):
                        d = futures[fut]
                        try:
                            dimension_results[d] = fut.result()
                        except Exception as exc:  # defensive; worker never raises
                            logger.error(
                                "dimension_worker_unexpected_error",
                                dimension=d,
                                error=str(exc),
                            )
                            dimension_results[d] = self._build_error_gap(d, str(exc))
            else:
                for d in pending:
                    dimension_results[d] = self._analyze_one_dimension(
                        d, workspace_id, num_frameworks, country, state,
                    )

        complete_results = [dimension_results[d] for d in GOVERNANCE_DIMENSIONS]
        all_retrieved = state.all_retrieved
        doc_chunks_per_dimension = state.doc_chunks_per_dimension
        llm_call_count = state.llm_call_count
        total_llm_latency = state.total_llm_latency

        for g in complete_results:
            if g.coverage == CoverageLevel.INSUFFICIENT_EVIDENCE:
                continue
            risk, reason = compute_risk(
                coverage=g.coverage,
                dimension=g.dimension,
                other_gaps=complete_results,
            )
            g.risk_level = risk
            g.risk_reason = reason
            # Recompute priority with compounding now that all dimensions are
            # known (Partial→Medium / Missing→High, escalated by cluster gaps).
            if g.module_2 is not None:
                g.module_2.priority = resolve_priority(
                    g.coverage,
                    g.dimension,
                    other_gaps=complete_results,
                )

        # Per-tier output statistics for reporting the Fully Covered token
        # reduction (module_2 payload size, the largest per-dimension output).
        tier_stats: dict[str, dict[str, Any]] = {}
        for g in complete_results:
            tier = g.coverage.value if g.coverage else "Unknown"
            entry = tier_stats.setdefault(tier, {"count": 0, "module2_chars": 0, "module2_avg_chars": 0.0})
            entry["count"] += 1
            if g.module_2 is not None:
                entry["module2_chars"] += len(g.module_2.model_dump_json())
        for entry in tier_stats.values():
            entry["module2_avg_chars"] = round(
                entry["module2_chars"] / entry["count"], 1
            ) if entry["count"] else 0.0
        logger.info("tier_output_stats", tier_stats=tier_stats)

        # Executive decision analytics — computed AFTER the priority recompute
        # above so highest_priority_dimensions reflects compounding escalation.
        decision_analytics = compute_decision_analytics(complete_results)
        logger.info("decision_analytics", **decision_analytics)

        consistency_report = self.consistency_validator.validate(
            gaps=complete_results,
            doc_chunks_per_dimension=doc_chunks_per_dimension,
        )

        for violation in consistency_report.violations:
            if violation.severity == "error":
                gap = next((g for g in complete_results if g.dimension == violation.dimension), None)
                if gap:
                    if gap.confidence_score > 0.5:
                        gap.confidence_score = round(gap.confidence_score * 0.8, 3)
                        gap.confidence_method += " | Reduced by consistency violation."

        total_similarity_scores = [
            r.get("similarity_score", 0.0)
            for r in all_retrieved
            if r.get("similarity_score") is not None
        ]

        result = GapAnalysisResult(
            analysis_id=analysis_id,
            workspace_id=workspace_id,
            document_name=document_name,
            frameworks_used=frameworks,
            governance_gaps=complete_results,
            summary=self._generate_summary(complete_results),
            total_retrieved=len(all_retrieved),
            retrieval_frameworks=frameworks,
            similarity_scores=total_similarity_scores,
            total_processing_time=time.time() - start_time,
            llm_latency=total_llm_latency,
            generated_by={
                "provider": self.provider.model_name,
                "tier": self.provider.tier,
            },
            consistency_report=consistency_report.to_dict(),
            llm_call_count=llm_call_count,
            tier_stats=tier_stats,
            decision_analytics=decision_analytics,
        )
        result.total_processing_time = time.time() - start_time

        logger.info(
            "gap_analysis_complete",
            analysis_id=analysis_id,
            dimensions_checked=len(complete_results),
            total_retrieved=len(all_retrieved),
            processing_time=result.total_processing_time,
            provider=self.provider.model_name,
            tier=self.provider.tier,
            llm_call_count=llm_call_count,
            module34_calls=llm_call_count - len(complete_results),
            consistency_passed=consistency_report.passed,
            consistency_score=consistency_report.score,
            decision_analytics=decision_analytics,
        )

        print_debug_summary()

        return result

    def _build_insufficient_gap(self, dimension: str) -> GovernanceGap:
        return GovernanceGap(
            dimension=dimension,
            coverage=CoverageLevel.INSUFFICIENT_EVIDENCE,
            gap_found=False,
            reason_flagged="Insufficient evidence retrieved from reference frameworks.",
            recommendation="No assessment possible without relevant framework context.",
            risk_level=RiskLevel.INSUFFICIENT_EVIDENCE,
            risk_reason="Insufficient Evidence",
            confidence_score=0.0,
            confidence_method="No retrieved evidence available.",
        )

    def _build_error_gap(self, dimension: str, error: str) -> GovernanceGap:
        """A dimension that failed analysis (LLM quota/provider/processing
        error) — explicitly NOT a finding. Keeps coverage as INSUFFICIENT
        EVIDENCE for schema compatibility but sets analysis_error so consumers
        can never confuse it with a genuine no-evidence verdict."""
        return GovernanceGap(
            dimension=dimension,
            coverage=CoverageLevel.INSUFFICIENT_EVIDENCE,
            gap_found=False,
            reason_flagged=f"Analysis failed: {error}",
            recommendation="Dimension could not be assessed — re-run the analysis when the LLM provider is available.",
            risk_level=RiskLevel.INSUFFICIENT_EVIDENCE,
            risk_reason="Analysis Error",
            confidence_score=0.0,
            confidence_method="No assessment produced — dimension analysis failed.",
            analysis_error=error,
        )

    def _generate_summary(self, gaps: list[GovernanceGap]) -> str:
        total = len(gaps)
        covered = sum(1 for g in gaps if g.coverage == CoverageLevel.COVERED)
        partial = sum(1 for g in gaps if g.coverage == CoverageLevel.PARTIAL)
        missing = sum(1 for g in gaps if g.coverage == CoverageLevel.MISSING)
        errored = [g for g in gaps if g.analysis_error]
        insufficient = sum(
            1 for g in gaps
            if g.risk_level == RiskLevel.INSUFFICIENT_EVIDENCE and not g.analysis_error
        )
        high_risk = sum(1 for g in gaps if g.risk_level == RiskLevel.HIGH)
        medium_risk = sum(1 for g in gaps if g.risk_level == RiskLevel.MEDIUM)
        dimensions_missing = [g.dimension for g in gaps if g.coverage == CoverageLevel.MISSING]
        dimensions_partial = [g.dimension for g in gaps if g.coverage == CoverageLevel.PARTIAL]

        parts = [
            f"Analysis of {total} governance dimensions:",
            f"{covered} Fully Covered, {partial} Partially Covered, {missing} Missing.",
        ]
        if high_risk > 0 or medium_risk > 0:
            parts.append(f"Risk levels: {high_risk} high-risk, {medium_risk} medium-risk.")
        if errored:
            first_err = (errored[0].analysis_error or "")[:120]
            parts.append(
                f"{len(errored)} dimension(s) could not be analysed "
                f"({', '.join(g.dimension for g in errored)}): {first_err}."
            )
        if insufficient > 0:
            parts.append(f"{insufficient} dimensions had insufficient evidence.")
        if dimensions_missing:
            parts.append(f"Missing: {', '.join(dimensions_missing)}.")
        if dimensions_partial:
            parts.append(f"Partial: {', '.join(dimensions_partial)}.")

        return " ".join(parts)
