from __future__ import annotations

import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import structlog
from pydantic import BaseModel, Field

from src import analysis_prompts
from src.consistency import (
    GAP_ASSERTION_THRESHOLD,
    ConsistencyValidator,
    detect_covered_synthesis_drift,
    detect_gap_assertions,
)
from src.deterministic import (
    NAMED_BODY_KEYWORDS,
    _chunk_matches_dimension,
    _has_keyword,
    _sentence_has_core_term,
    _split_sentences,
    is_low_information_fragment,
    text_contains_mechanism,
)
from src.evidence_agreement import analyze_evidence_agreement, compute_evidence_agreement_score
from src.evidence_strength import (
    TIER_OBLIGATORY,
    coverage_from_profile,
    depth_from_profile,
    describe_risk_basis,
    detect_mechanisms,
    detect_nonbinding_document,
)
from src.framework_router import (
    resolve_dimension_frameworks,
    resolve_frameworks,
    resolve_regional_frameworks,
)
from src.framework_salience import framework_count, rank_absent
from src.grading import (
    SOURCE_UNENFORCED,
    SOURCE_VOLUNTARY,
    apply_mechanism_gate,
    sentence_function,
    verdict_confidence,
)
from src.grading import build_provision_profile as build_provision_profile
from src.llm_provider import LLMProvider
from src.mechanism_adjudication import adjudicate_batch
from src.models import (
    BestPractices,
    CalibratedConfidence,
    CoverageLevel,
    EvidenceItem,
    GovernanceGap,
    ImplementationDepth,
    IncidentMatch,
    InternationalExample,
    Module1Evaluation,
    Module2Recommendation,
    Module3Implementation,
    Module3Phase,
    Module4CaseIntelligence,
    ModuleCitation,
    Priority,
    RetrievedEvidence,
    RiskLevel,
)
from src.provider_router import generate_with_retry, get_provider, log_run_summary
from src.retrieval import Module34RetrievalResult, ModuleRetrievalResult, RetrievalPipeline
from src.utils import strip_chunk_id_citations
from src.vectorstore import VectorStore
from src.verify import (
    classify_narrative_citations,
    detect_division_vocabulary,
    verify_citation,
)

# Bounded concurrency for the per-dimension analysis loop. The 8 dimensions
# used to run strictly sequentially (up to 16 LLM calls back to back); now
# they run in a worker pool while provider_router paces the actual request
# rate underneath — one RPM throttle per Gemini key with round-robin key
# selection, so 8 workers spread across 4 keys use all the keys' headroom
# (default 8 in flight, env-tunable) without ever exceeding one key's
# free-tier ceiling.
ANALYSIS_MAX_CONCURRENCY = int(os.getenv("ANALYSIS_MAX_CONCURRENCY", "3"))

#: One Module 3+4 request for every gapped dimension of a run instead of one
#: each, after the workspace-wide mechanism check. Same prompts per dimension,
#: same handling of every answer; see _analyze_pending_batched.
BATCH_LLM_CALLS = os.getenv("BATCH_LLM_CALLS", "1").strip().lower() not in ("0", "false", "no")
#: Module 1+2 in one shared request too. Off by default: measured on the first
#: full batch (Rwanda, 26 Sep), a dimension sharing a reply cited about a third
#: fewer passages than it does on its own — 4.0 / 3.0 / 3.0 per Covered /
#: Partial / Missing cell against 5.6 / 5.2 / 4.0 — and an instruction to cite
#: in full did not bring them back. On, a run costs 3 requests; off, about 10.
BATCH_EVALUATION = os.getenv("BATCH_EVALUATION", "0").strip().lower() in ("1", "true", "yes")


def evaluation_mode() -> str:
    """How Module 1+2 is asked on this run: in a shared reply or one per dimension.

    Recorded with every cached dimension, because the two cite differently and a
    resumed run must not stitch one kind of answer to the other.
    """
    return "shared" if BATCH_LLM_CALLS and BATCH_EVALUATION else "per_dimension"


#: Output room for a batched reply: the 8,192 tokens a single call is given,
#: once for each of eight dimensions. That is also the model's own ceiling
#: (65,536), and anything lower would leave a dimension less room in a batch
#: than it had on its own.
BATCH_MAX_OUTPUT_TOKENS = int(os.getenv("BATCH_MAX_OUTPUT_TOKENS", "65536"))

# Substantive-specificity threshold for auto-attached citations. Keyword
# relevance admits PROCEDURAL authority provisions too ("the Minister may
# approve/support AI data centres", "shall promote measures to facilitate the
# production, collection, management, distribution, utilization of learning
# data"), which touch a dimension without imposing anything on it. The gate
# requires a chunk's mechanism-bearing SENTENCES to sit semantically close to
# the dimension's profile above this bar before the chunk can be attached as a
# requirement citation ("procedural authority ≠ substantive governance
# mechanism").
# Calibrated against BAAI/bge-small-en-v1.5 on the Korean AI Basic Act
# passages: genuine dimension mechanisms score 0.64-0.80 against their
# dimension's aspects, procedural provisions 0.48-0.59 — a clean split at
# ~0.62. Model-dependent; env-tunable.
SUBSTANTIVE_RELEVANCE_THRESHOLD = float(os.getenv("SUBSTANTIVE_RELEVANCE_THRESHOLD", "0.62"))


# Sentence boundary heuristic for the substantive gate: a chunk can be a
# long legal passage where only one sentence carries the actual governance
# mechanism ("shall report annual energy consumption") while the rest is
# procedural boilerplate. Whole-chunk similarity dilutes the mechanism
# signal, so the gate embeds the mechanism-bearing sentences instead.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _mechanism_sentences(text: str) -> list[str]:
    """Split `text` into sentences, keeping only those carrying mechanism
    language (named body / reporting / enforcement / obligation) so the
    substantive gate scores the actual governance content rather than the
    surrounding procedural boilerplate."""
    if not text:
        return []
    return [
        s.strip()
        for s in _SENTENCE_SPLIT_RE.split(text)
        if s.strip() and text_contains_mechanism(s)
    ]


# ── Definitional/glossary exclusion for fallback citations ──────────────
# Cheap first-pass filter for auto-attached citations. A definitions section
# ("The terms used in this Act are as follows: 1. 'Artificial Intelligence'
# ...") ranks on broad vocabulary and passes the keyword dimension gate (a
# defined term like "environment" appears somewhere in the list), yet carries
# zero implementation content — the confirmed live failure on the Korea
# Environmental Sustainability card. Detected BEFORE the semantic gates run:
# the phrase/heading signal is conclusive, and the numbered-quoted-term
# structure is a cheap structural backstop for glossaries that do not use
# the "terms used in this Act" formulation.
_DEFINITION_SECTION_RE = re.compile(
    r"terms? used in this (?:act|law|regulation|rule|standard|guideline|framework|directive)|"
    r"^\s*(?:definitions?|interpretation|glossary)\b[^\n]*$",
    re.IGNORECASE | re.MULTILINE,
)
_DEFINITION_LIST_ITEM_RE = re.compile(r"^\s*\d+\.\s*[\"\u201c\u2018']", re.MULTILINE)


def _is_definitional_or_glossary(text: str) -> bool:
    """True when a chunk is primarily a definitions/glossary section.

    Detected by (a) the "terms used in this Act/..." formulation or a
    Definitions/Interpretation/Glossary heading, or (b) a numbered list of
    quoted terms (glossary structure) with at least three items. Cheap
    string/regex checks only — runs before any embedding work.
    """
    if not text:
        return False
    if _DEFINITION_SECTION_RE.search(text):
        return True
    return len(_DEFINITION_LIST_ITEM_RE.findall(text)) >= 3


def _cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _reply_was_malformed(exc: BaseException) -> bool:
    """Whether the model answered but its reply did not fit the schema."""
    from pydantic import ValidationError

    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, ValidationError):
            return True
        seen = seen.__cause__
    return False


def _split_can_help(exc: BaseException) -> bool:
    """Whether a smaller request could succeed where this batch failed.

    Only when the reply itself was the trouble: malformed, cut short, or out
    of time. An overloaded model, a spent quota or a dropped connection fails
    a half exactly as it failed the whole, and the provider counts every
    attempt against the day's allowance, answered or not — on 24 Sep an
    outage spent all 100 of five keys' requests for 15 answers, splitting
    503-refused batches into more 503-refused halves.
    """
    from pydantic import ValidationError

    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, ValidationError):
            return True
        if "timeout" in type(seen).__name__.lower() or "timed out" in str(seen).lower():
            return True
        seen = seen.__cause__
    return False


@dataclass
class _DimensionCall:
    """One dimension's Module 1+2 request, and what its answer is read against."""

    dimension: str
    retrieval: Any
    determined: dict[str, Any] | None
    workspace_id: str
    dimension_definition: str
    system_prompt: str
    prompt: str


@dataclass
class _Module34Call:
    """One gapped dimension's Module 3+4 request, and the gap its answer fills."""

    dimension: str
    gap: Any
    retrieval: Any
    workspace_id: str
    dimension_definition: str
    dimension_verdict: str
    system_prompt: str
    prompt: str


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
        self.module34_call_count = 0
        self.total_llm_latency = 0.0


# Words that never denote an institution when they appear capitalized in a
# recommendation (used by the Module 2 → Module 3 agency cross-reference).
# NOTE: "ai" is deliberately ABSENT. It used to be here, which made it
# structurally impossible to identify any institution whose name begins with
# "AI" — the AI Office, the AI Board, an AI Safety Institute, an AI Authority.
# Those are precisely the bodies that AI legislation creates, so in an
# AI-governance tool this skipped exactly the wrong names: the EU AI Act,
# which establishes the AI Office and names it 56 times, reported "Not
# specified by policy — implementation responsibility should be assigned by
# the adopting government."
#
# Nothing is lost by removing it. The designator gate below already rejects
# "AI Governance Framework" and "AI Act" (no organizational designator),
# while "AI Office" and "AI Board" pass on "office"/"board" — which is the
# distinction the skip list was reaching for in the first place.
_MODULE2_AGENCY_SKIP = {
    "the",
    "and",
    "task",
    "phase",
    "step",
    "such",
    "in",
    "of",
    "to",
    "a",
    "an",
    "data",
    "public",
    "national",
    "new",
    "this",
    "standard",
    "standards",
    "body",
    "bodies",
    "each",
    "for",
    "with",
    "across",
    "government",
    "all",
    "high",
    "risk",
    "use",
    "using",
    "ml",
}

# Organizational designators. A multi-word capitalized phrase is only
# treated as an institution when it contains one of these — otherwise a
# generic noun phrase like "Digital Public Infrastructure" or "Generative
# AI" (which appears verbatim in policy documents all the time) would be
# mistaken for a body being tasked. Single-token acronyms ("BIS", "CDEI")
# and CamelCase short forms ("MeitY") are handled separately by the
# capital-heavy pattern and do not need a designator.
_MODULE2_AGENCY_DESIGNATORS = {
    "ministry",
    "department",
    "bureau",
    "board",
    "authority",
    "commission",
    "agency",
    "institute",
    "council",
    "office",
    "foundation",
    "centre",
    "center",
    "directorate",
    "secretariat",
    "committee",
    "division",
    "cell",
    "administration",
    "regulator",
    "parliament",
    "cabinet",
    "task force",
}


# A designator alone does not make an institution. Legal drafting is full of
# phrases that end in one without naming a body: "Cabinet Order" and
# "... Administrative Agency Act" are instruments, while "Term of Office",
# "Delegation of Authority" and "Exercising Authority" use the designator as an
# ordinary noun. All six appeared as candidates on the Japan corpus.
_INSTRUMENT_TAIL = {
    "act",
    "order",
    "rules",
    "rule",
    "regulation",
    "regulations",
    "law",
    "code",
    "bill",
    "plan",
    "guidelines",
    "standard",
    "standards",
    "policy",
    "agreement",
    "treaty",
    "convention",
}
_ABSTRACT_HEAD = {
    "term",
    "terms",
    "exercising",
    "exercise",
    "delegation",
    "general",
    "matters",
    "scope",
    "establishment",
    "appointment",
    "composition",
    "organization",
    "organisation",
    "duties",
    "functions",
    "powers",
    "local",
    "special",
    "relevant",
    "respective",
    "necessary",
}


def _is_institution_phrase(phrase: str) -> bool:
    """Reject designator-bearing phrases that do not name a body."""
    tokens = [t.strip(",.").lower() for t in phrase.split() if t.strip(",.")]
    if len(tokens) < 2:
        return False
    if tokens[-1] in _INSTRUMENT_TAIL:
        return False
    if tokens[0] in _ABSTRACT_HEAD:
        return False
    # A real name carries a qualifier that is neither a designator nor a
    # connective — "Personal Information Protection Commission" has three,
    # "Term of Office" has none once "term" is excluded above.
    connective = {"of", "for", "and", "the", "on", "in"}
    qualifiers = [t for t in tokens if t not in connective and t not in _MODULE2_AGENCY_DESIGNATORS]
    return len(qualifiers) >= 1


def document_named_bodies(
    chunks: list[dict[str, Any]],
    dimension: str,
    limit: int = 6,
) -> list[str]:
    """Institutions the document names in passages about THIS dimension.

    Module 3 asks the model to name the body responsible for implementing a
    dimension, forbids it three times from inventing one, and then shows it two
    document chunks. When the passage naming the body is not among those two —
    which it usually is not — "none_identified" is the only answer the model can
    safely give, and every gapped dimension reports "Not specified by policy"
    for documents that plainly do name institutions. Japan's corpus names the
    Personal Information Protection Commission 53 times and an AI Strategic
    Headquarters 10 times, and all three gapped dimensions still came back
    empty.

    So the candidates are extracted deterministically and shown to the model.
    Nothing is invented: each name is a verbatim capitalised phrase carrying an
    organisational designator, taken from a chunk that passes the same
    dimension-grounding gate used everywhere else, ordered by how often it
    appears.

    Proximity is NOT assignment, and this function does not claim otherwise —
    a privacy regulator appearing in an Inclusivity passage is not responsible
    for Inclusivity. The model still decides, and _verify_responsible_agency
    still re-grounds whatever it picks.
    """
    counts: dict[str, int] = {}
    for c in chunks:
        text = (c.get("text") or "") if isinstance(c, dict) else ""
        if not text or not _chunk_matches_dimension(text, dimension):
            continue
        for m in re.finditer(
            r"\b[A-Z][a-zA-Z&.'\-]+(?:\s+(?:of|for|and)?\s*[A-Z][a-zA-Z&.'\-]+){1,5}\b",
            text,
        ):
            # A capitalised word starting the NEXT sentence gets swept into the
            # match ("... Commission. The"); cut at the sentence boundary.
            phrase = " ".join(m.group(0).split())
            phrase = re.split(r"(?<=[.;:])\s", phrase)[0].strip(" .,;:")
            if not phrase:
                continue
            # STRIP leading filler rather than discarding the match. re.finditer
            # is non-overlapping, so "The Personal Information Protection
            # Commission" consumes the span; rejecting it because it starts
            # with "The" meant the real name was never seen at all, and only
            # occurrences that happened to lack an article were found.
            tokens = phrase.split()
            while tokens and tokens[0].lower() in _MODULE2_AGENCY_SKIP:
                tokens.pop(0)
            if len(tokens) < 2:
                continue
            phrase = " ".join(tokens)
            if not any(
                tok.lower().strip(",.") in _MODULE2_AGENCY_DESIGNATORS for tok in phrase.split()
            ):
                continue
            if not _is_institution_phrase(phrase):
                continue
            counts[phrase] = counts.get(phrase, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    # Drop a candidate that is contained in a better-ranked one: the regex
    # happily matches "Protection Commission" inside "Personal Information
    # Protection Commission", and offering both invites the model to cite the
    # truncated form.
    kept: list[str] = []
    for name, _ in ranked:
        if any(name.lower() in k.lower() for k in kept):
            continue
        kept.append(name)
        if len(kept) >= limit:
            break
    return kept


def _has_named_body_keyword_ocr(text: str) -> bool:
    """NAMED_BODY_KEYWORDS, matched through OCR word-splitting.

    _has_keyword's whole-word regex is correct on clean text and blind on
    extracted PDF text. Stem entries ("minister*") keep their trailing-suffix
    behaviour here.
    """
    for kw in NAMED_BODY_KEYWORDS:
        stem = kw.rstrip("*")
        core = r"\s*".join(re.escape(ch) for ch in stem if not ch.isspace())
        suffix = r"\w*" if kw.endswith("*") else r"(?:s)?"
        if re.search(r"\b" + core + suffix + r"\b", text or "", re.IGNORECASE):
            return True
    return False


@lru_cache(maxsize=512)
def _ocr_tolerant_phrase(phrase: str) -> re.Pattern:
    """Match a phrase even when PDF extraction split its words apart.

    Whitespace is permitted between any two characters, so "AI Office" also
    matches "AI Off ice" and "A I Offi ce". Word boundaries are kept at the
    ends so "board" still cannot match inside "keyboard".

    Cached because agency names repeat across all eight dimensions of a run.
    """
    core = r"\s*".join(re.escape(ch) for ch in phrase.strip() if not ch.isspace())
    return re.compile(r"\b" + core + r"\b", re.IGNORECASE)


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
            if not any(tok.lower() in _MODULE2_AGENCY_DESIGNATORS for tok in phrase.split()):
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
                # A bare two-letter acronym is never an institution on its own.
                # "AI" is the one that matters here — it is in every sentence
                # of every document this tool reads, so accepting it would
                # name "AI" as the responsible agency. Real acronyms in this
                # space are three or more letters (BIS, CDEI, MeitY, NIST).
                if len(token) < 3:
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


CORE_DIMENSIONS = {"Transparency", "Accountability", "Privacy", "Safety"}

DIMENSION_CLUSTERS = [
    {"Transparency", "Accountability"},
    {"Privacy", "Safety"},
    {"Fairness", "Inclusivity"},
    {"Human Autonomy", "Environmental Sustainability"},
]

# Fully Covered tier: fixed opening line for the Best Practices block.
# Code-emitted (deterministic), never LLM-written.
BEST_PRACTICES_OPENING = (
    "This policy already aligns strongly with international governance "
    "expectations. The following international practices may further "
    "strengthen future revisions, but no critical governance gaps were "
    "identified."
)

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
    # card, future dashboard visualisations (pie charts, depth gauges,
    # country comparisons) and the research paper's evaluation section.
    decision_analytics: dict[str, Any] | None = None


# Ordinal ordering of ImplementationDepth stages (low → high). Used ONLY for
# ordering, comparisons, and the weakest-dimension staged-depth rule —
# never averaged (stages are ordinal categories; a mean of ranks rounded to a
# label is statistically invalid).
DEPTH_RANK = {
    ImplementationDepth.UNADDRESSED: 0,
    ImplementationDepth.EMERGING: 1,
    ImplementationDepth.DELEGATED: 2,
    ImplementationDepth.DEVELOPING: 3,
    ImplementationDepth.ESTABLISHED: 4,
}


# Score contributed by each stage to the 0-100 composite index.
#
# The index used to be `100 * sum(ranks) / (3 * n)` — a linear average of the
# ordinal ranks above, which the comment on DEPTH_RANK explicitly forbids
# ("never averaged ... a mean of ranks is statistically invalid"). The code
# did exactly what its own comment ruled out, and the consequence is not
# pedantic: a linear mapping asserts that the step from Unaddressed to
# Emerging is worth precisely as much as the step from Operationalized to
# Institutionalized. It is not.
#
# The stages are scored explicitly instead, so the modelling choice is visible
# and arguable rather than smuggled in as arithmetic. The spacing follows the
# obligation / precision / delegation axes the tier system is built on:
#
#   Unaddressed        0   the dimension is absent.
#   Emerging          50   recognised and committed to, but nobody owns it and
#                          no duty exists. Governed in intent only.
#   Delegated         65   an owner or a duty exists, but not a working regime:
#                          a named institution carries it (T2 Assigned), or a
#                          lone binding duty stands with nothing enforcing it.
#   Operationalized   78   binding duty AND the force bar — a regime, not a
#                          single provision.
#   Institutionalized 100  the duties are backed by enforcement or oversight.
#
# Why Delegated exists. Emerging previously absorbed three materially different
# profiles and paid them all 50: India's Inclusivity (a real binding duty),
# India's Human Autonomy (a named institution, no duty) and India's Fairness
# (a bare principle) were indistinguishable in the index while their own
# narratives said plainly different things. That is unreadable to a reviewer
# comparing two dimensions in the same document.
#
# It is also the axis the cited theory already names: Abbott & Snidal separate
# obligation from DELEGATION, and n_institutional measures delegation directly.
# The counter was computed and then discarded at staging. This stage surfaces
# it rather than inventing a new signal.
#
# Calibration check against the live corpora: EU 91.0 -> 92.9, Japan 75.8 ->
# 77.6, India 63.2 -> 67.0. Ordering and separation are preserved and the
# ceiling is untouched — the T3/T4 force bar is not moved, so a document that
# binds nobody still cannot reach Operationalized, and India's Fairness stays
# at 50 because it genuinely has no duty and no owner.
DEPTH_STAGE_SCORE = {
    ImplementationDepth.UNADDRESSED: 0.0,
    ImplementationDepth.EMERGING: 50.0,
    ImplementationDepth.DELEGATED: 65.0,
    ImplementationDepth.DEVELOPING: 78.0,
    ImplementationDepth.ESTABLISHED: 100.0,
}


# Depth and breadth are deliberately NOT combined into one number. A version
# that scaled each stage score by the share of mechanisms addressed was
# considered and not adopted; breadth is reported as its own index (see
# compute_decision_analytics) so a narrow statute that binds hard and a broad
# strategy that binds nobody stay distinguishable.
# Reverse map: rank → stage label, for weakest-dimension staging.
RANK_TO_LABEL = {rank: stage.value for stage, rank in DEPTH_RANK.items()}

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
        g
        for g in gaps
        if g.coverage in (CoverageLevel.COVERED, CoverageLevel.PARTIAL, CoverageLevel.MISSING)
    ]

    covered = sum(1 for g in gaps if g.coverage == CoverageLevel.COVERED)
    partial = sum(1 for g in gaps if g.coverage == CoverageLevel.PARTIAL)
    missing = sum(1 for g in gaps if g.coverage == CoverageLevel.MISSING)
    insufficient = sum(
        1
        for g in gaps
        if g.coverage == CoverageLevel.INSUFFICIENT_EVIDENCE and not g.analysis_error
    )
    failed = sum(1 for g in gaps if g.analysis_error)

    # ── Governance depth index ─────────────────────────────────────────
    # A continuous 0-100 composite so the gradient between stages is visible
    # for dashboards. Mean of explicit stage SCORES, not of ordinal ranks —
    # see DEPTH_STAGE_SCORE for why the linear rank average was wrong.
    #
    # A single weakest-dimension LABEL used to be reported alongside this
    # (an overall stage only claimable when every dimension reached it). It
    # was never surfaced anywhere in the frontend and duplicated what the
    # stage histogram already shows per-dimension, so it was dropped rather
    # than carried as dead weight.
    assessed_ranks = [DEPTH_RANK.get(g.implementation_depth, 0) for g in assessed]
    if assessed_ranks:
        stage_scores = [DEPTH_STAGE_SCORE.get(g.implementation_depth, 0.0) for g in assessed]
        implementation_depth_index = round(sum(stage_scores) / len(stage_scores), 1)
        # Full stage histogram (pie/histogram-ready).
        depth_distribution = {
            label: sum(1 for r in assessed_ranks if r == rank)
            for rank, label in RANK_TO_LABEL.items()
        }
    else:
        implementation_depth_index = 0.0
        depth_distribution = dict.fromkeys(RANK_TO_LABEL.values(), 0)

    # ── Coverage breadth: the SECOND axis ────────────────────────────────
    # How much of what each dimension needs the document addresses AT ALL,
    # independent of the force behind it. Reported beside the force index
    # rather than folded into it, because the interesting cases are exactly
    # the ones where the two diverge: a soft-law instrument that addresses
    # nearly everything and binds almost none of it reads 85/55, and a narrow
    # statute that binds hard reads 40/90. A single number cannot say either.
    #
    # Deliberately NOT tier-weighted. Weighting breadth by force would fold
    # the force axis back into it and collapse the distinction this exists to
    # draw. Force is the other number.
    mech_met = sum(len(g.mechanisms_present or {}) for g in assessed)
    mech_total = mech_met + sum(len(g.mechanisms_absent or []) for g in assessed)
    coverage_index = round(100.0 * mech_met / mech_total, 1) if mech_total else 0.0
    # Of the mechanisms that ARE present, how many are carried by an actual
    # duty (tier >= 3) rather than merely mentioned. The bridge between the
    # two axes, and the honest answer to "yes, but is any of it binding?"
    mech_binding = sum(
        1
        for g in assessed
        for tier in (g.mechanisms_present or {}).values()
        if tier >= TIER_OBLIGATORY
    )
    binding_share = round(100.0 * mech_binding / mech_met, 1) if mech_met else 0.0

    # ── Highest priority dimensions (Critical/High, most urgent first) ──
    high_priority = [
        g
        for g in gaps
        if g.module_2 is not None and g.module_2.priority in (Priority.CRITICAL, Priority.HIGH)
    ]
    high_priority.sort(key=lambda g: PRIORITY_RANK.get(g.module_2.priority, 9))
    highest_priority_dimensions = [g.dimension for g in high_priority]

    # ── Strongest dimension (highest depth, confidence tie-break) ──
    strongest_dimension = ""
    if assessed:
        strongest = max(
            assessed,
            key=lambda g: (DEPTH_RANK.get(g.implementation_depth, 0), g.confidence_score),
        )
        strongest_dimension = strongest.dimension

    avg_confidence = (
        round(sum(g.confidence_score for g in assessed) / len(assessed), 3) if assessed else 0.0
    )

    return {
        "covered": covered,
        "partial": partial,
        "missing": missing,
        "insufficient_evidence": insufficient,
        "analysis_failed": failed,
        "coverage_index": coverage_index,
        "mechanisms_met": mech_met,
        "mechanisms_total": mech_total,
        "mechanisms_binding": mech_binding,
        "binding_share": binding_share,
        "implementation_depth_index": implementation_depth_index,
        "depth_distribution": depth_distribution,
        "assessed_dimensions": len(assessed),
        "average_confidence": avg_confidence,
        "highest_priority_dimensions": highest_priority_dimensions,
        "strongest_dimension": strongest_dimension,
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
        e.similarity_score
        for e in evidence_list
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
    # Diversity SATURATES on the number of distinct sources and is deliberately
    # independent of how much evidence was found.
    #
    # It used to be `unique_sources / max(5, total_evidence) * 2`, which divides
    # by volume: the same single authoritative document scored 0.4 with 3
    # evidence items but 0.125 with 16. Combined with cross_source_agreement
    # below (which had the same divisor) the penalty landed twice inside a
    # seven-factor geometric mean, so retrieving MORE verified, high-similarity,
    # fully-cited evidence actively destroyed confidence — measured at 0.735
    # for 2 items falling to 0.462 for 16.
    #
    # That inverted the intended meaning and penalised exactly the documents
    # that are best evidenced: a dense binding statute, whose provisions all
    # come from the one instrument being assessed, scored lower than a thin
    # strategy with a couple of scattered citations. Three distinct sources is
    # treated as full diversity; beyond that adds nothing.
    cal.evidence_diversity_factor = round(min(1.0, unique_sources / 3.0), 3)

    # evidence_pairs is None only when the caller never computed pairwise
    # agreement at all — that's the case where a flat guess used to stand
    # in. An explicitly empty list ([], e.g. only one evidence item exists)
    # is real information and routes through the real function, which
    # returns 1.0 for "nothing to disagree with" — a more honest default
    # than a blind 0.5.
    if evidence_pairs is not None:
        cal.evidence_agreement_factor = compute_evidence_agreement_score(evidence_pairs)
    else:
        cal.evidence_agreement_factor = 0.5

    if retrieval_stability is not None:
        if retrieval_stability.is_stable:
            cal.retrieval_stability_factor = retrieval_stability.semantic_stability
        else:
            cal.retrieval_stability_factor = max(0.1, retrieval_stability.semantic_stability * 0.5)
    else:
        # No repeated-retrieval stability run available for this call (that
        # would triple retrieval cost per dimension). Proxy from the REAL
        # spread of this evidence set's own similarity scores instead of a
        # flat guess: a tight, high cluster of scores is genuine signal the
        # retrieval consistently found strongly relevant evidence; a wide
        # or low spread is genuine signal it didn't. Mean-minus-std-dev is
        # the standard "discount for variance" idiom — never a placeholder.
        sims = list(similarity_scores) if similarity_scores else []
        if len(sims) >= 2:
            mean_sim = sum(sims) / len(sims)
            variance = sum((s - mean_sim) ** 2 for s in sims) / len(sims)
            cal.retrieval_stability_factor = round(max(0.0, min(1.0, mean_sim - variance**0.5)), 3)
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

    # Corroboration across independent sources. Also volume-independent, for
    # the same reason as evidence_diversity_factor above — this was previously
    # `unique_sources / total_evidence`, the second of the two volume divisors
    # that made additional evidence lower the score.
    #
    # Single-source evidence is not untrustworthy (an assessment of ONE
    # uploaded instrument is legitimately single-source), so the floor is 0.6
    # rather than a near-zero ratio; each additional independent source that
    # corroborates the finding adds to it.
    if unique_sources <= 0:
        cal.cross_source_agreement = 0.0
    else:
        cal.cross_source_agreement = round(min(1.0, 0.6 + 0.2 * (unique_sources - 1)), 3)

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


def _is_assessed_gap(gap: GovernanceGap) -> bool:
    """True when a neighbouring dimension is a REAL, ASSESSED governance gap.

    The cluster-compounding rules in compute_risk and resolve_priority
    escalate a dimension's risk/priority when a related dimension is also
    weak. The test used to be `coverage != COVERED`, which is silently TRUE
    for INSUFFICIENT_EVIDENCE — the value assigned when a dimension could not
    be analysed at all (LLM quota exhaustion, provider error).

    That let a failure of OUR pipeline masquerade as a finding about the
    country: a run where several dimensions errored out would escalate the
    risk and priority of every surviving dimension in the same cluster,
    reporting a policy as higher-risk because the tool broke, not because the
    document is weak. Partial-failure runs were common enough (one country
    lost all 8 dimensions to quota, another 6 of 8) that this was actively
    corrupting results.

    Only PARTIAL and MISSING are genuine assessed gaps. A dimension carrying
    analysis_error is excluded regardless of its coverage label.
    """
    if getattr(gap, "analysis_error", None):
        return False
    return gap.coverage in (CoverageLevel.PARTIAL, CoverageLevel.MISSING)


def compute_risk(
    coverage: CoverageLevel,
    dimension: str,
    other_gaps: list[GovernanceGap] | None = None,
    basis: str | None = None,
) -> tuple[RiskLevel, str]:
    """Risk level from coverage tier + cluster compounding.

    `basis` replaces the generic reason sentence with one describing the
    document's actual evidence (see describe_risk_basis). The LEVEL is
    unaffected by it — only how the level is explained. Without a basis the
    original wording is kept, so the degenerate paths still read sensibly.
    """
    if coverage == CoverageLevel.INSUFFICIENT_EVIDENCE:
        return RiskLevel.INSUFFICIENT_EVIDENCE, "Too little evidence to assess this dimension."

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

    if basis:
        reason = basis

    if coverage != CoverageLevel.COVERED and other_gaps:
        cluster = next((c for c in DIMENSION_CLUSTERS if dimension in c), None)
        if cluster:
            any_gap = any(
                g.dimension in cluster and g.dimension != dimension and _is_assessed_gap(g)
                for g in other_gaps
            )
            if any_gap:
                if base == RiskLevel.LOW:
                    base = RiskLevel.MEDIUM
                elif base == RiskLevel.MEDIUM:
                    base = RiskLevel.HIGH
                reason += (
                    " Related dimensions in the same cluster are also weak, so "
                    "a failure here has no neighbouring safeguard to fall back on."
                )

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
        # Same correctness rule as compute_risk: an unanalysed dimension is
        # not evidence of a governance gap. See _is_assessed_gap.
        any_gap = any(
            g.dimension in cluster and g.dimension != dimension and _is_assessed_gap(g)
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
#   - implementation depth: Unaddressed / Emerging lengthen ramp-up;
#     Operationalized / Institutionalized shorten it.
#   - responsible-agency grounding: no named body means designation time;
#     a document-named owner shortens it.
#   - phase scope (step count) widens/narrows the range.
# Phase 2 chains after Phase 1 (sequential, not overlapping).

DEPTH_SLOW = {ImplementationDepth.UNADDRESSED, ImplementationDepth.EMERGING}
DEPTH_FAST = {ImplementationDepth.DEVELOPING, ImplementationDepth.ESTABLISHED}


def estimate_phase_timelines(
    coverage: CoverageLevel,
    operational_mechanisms: list[str],
    depth: ImplementationDepth | None,
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
        if depth in DEPTH_SLOW:
            adj += 3
            reasons.append(f"low depth ({depth.value}) lengthens ramp-up")
        elif depth in DEPTH_FAST:
            adj -= 2
            reasons.append(f"high depth ({depth.value}) shortens the runway")
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


class GapAnalyzer:
    def __init__(
        self,
        vector_store: VectorStore,
        provider: LLMProvider | None = None,
    ):
        self.vector_store = vector_store
        self.provider = provider or get_provider()

        self.retrieval_pipeline = RetrievalPipeline(vector_store)
        self.consistency_validator = ConsistencyValidator()

    # ── Combined Module 1 + Module 2 LLM schema ─────────────────────────

    @staticmethod
    def _get_combined_module_schema() -> type[BaseModel]:
        class CitationSchema(BaseModel):
            chunk_id: str
            quote: str
            page_number: int | None = None
            # What this passage establishes for the dimension. The response is
            # schema-constrained, so a field absent HERE is stripped however
            # firmly the prompt asks for it — which is why `claim` came back
            # empty on all 168 citations after the prompt was updated.
            claim: str = ""

        class InternationalExampleSchema(BaseModel):
            practice: str
            country_or_source: str
            chunk_id: str
            quote: str
            page_number: int | None = None
            # How the example relates to what THIS document already does. The
            # prompt has asked for it all along; without the field the schema
            # discarded every answer, the failure recorded for `claim` too.
            alignment: str = ""

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
            # Optional dissent from the computed verdict. Recorded for review
            # and calibration; deliberately does NOT change the reported
            # result — see _compute_deterministic_verdict for why the verdict
            # stays deterministic.
            verdict_challenge: str = ""
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
        pairs: list[tuple[str, str, str, dict[str, Any]]] = []
        citation_dicts: list[dict[str, Any]] = []
        for ex in examples:
            if isinstance(ex, dict):
                practice = ex.get("practice", "") or ""
                country = ex.get("country_or_source", "") or ""
                chunk_id = ex.get("chunk_id", "") or ""
                quote = ex.get("quote", "") or ""
                page = ex.get("page_number")
                alignment = ex.get("alignment", "") or ""
            else:
                practice = getattr(ex, "practice", "") or ""
                country = getattr(ex, "country_or_source", "") or ""
                chunk_id = getattr(ex, "chunk_id", "") or ""
                quote = getattr(ex, "quote", "") or ""
                page = getattr(ex, "page_number", None)
                alignment = getattr(ex, "alignment", "") or ""

            if not practice.strip():
                continue
            # Same label→real-id translation every other citation path uses:
            # the model may echo a prompt label (PRAC-2) instead of the real
            # chunk id; without this, a PRAC-style id fails chunk lookup and
            # the example is silently dropped even though it was grounded.
            if label_map and chunk_id in label_map:
                chunk_id = label_map[chunk_id]
            pairs.append(
                (
                    practice,
                    country,
                    alignment,
                    {"chunk_id": chunk_id, "quote": quote, "page_number": page},
                )
            )
            citation_dicts.append({"chunk_id": chunk_id, "quote": quote, "page_number": page})

        citations = self._verify_module_citations(citation_dicts, source_type="framework")
        for (practice, country, alignment, _raw), citation in zip(pairs, citations, strict=True):
            # Drop sentinel / empty / nonexistent-chunk entries — the model
            # declined or fabricated; neither may surface as a real practice.
            # NOTE: _verify_module_citations keeps the chunk_id on missing
            # chunks (marked unverified), so re-check existence explicitly.
            if citation.no_citation or not citation.chunk_id:
                continue
            if self.vector_store.get_chunk(citation.chunk_id) is None:
                continue
            verified.append(
                InternationalExample(
                    practice=practice.strip(),
                    country_or_source=country.strip(),
                    reference=citation.source,
                    alignment=alignment.strip(),
                    citation=citation,
                )
            )
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
            # What this passage is evidence FOR. Carried through because a
            # quote nobody can tie to a step cannot be checked.
            claim = (c.get("claim", "") if isinstance(c, dict) else getattr(c, "claim", "")) or ""
            if self._is_no_citation_entry(chunk_id, quote):
                verified_list.append(
                    ModuleCitation(
                        quote="",
                        chunk_id="",
                        source=default_source,
                        source_type=source_type,
                        page_number=None,
                        no_citation=True,
                        verification={
                            "passed": False,
                            "method": "no_citation_available",
                            "failure_reason": (
                                "No supporting passage was found in the retrieved "
                                "context — no citation was fabricated."
                            ),
                        },
                    )
                )
                continue
            if not chunk_id:
                verified_list.append(
                    ModuleCitation(
                        quote=quote,
                        chunk_id="",
                        source=default_source,
                        source_type=source_type,
                        verified=False,
                        verification={
                            "passed": False,
                            "failure_reason": "The analysis quoted this without saying where it came from.",
                        },
                    )
                )
                continue

            chunk = self.vector_store.get_chunk(chunk_id)
            if chunk is None:
                verified_list.append(
                    ModuleCitation(
                        quote=quote,
                        chunk_id=chunk_id,
                        source=default_source,
                        source_type=source_type,
                        verified=False,
                        verification={
                            "passed": False,
                            "failure_reason": "The cited passage could not be found in the indexed documents.",
                        },
                    )
                )
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
            )
            verified_list.append(
                ModuleCitation(
                    quote=quote,
                    chunk_id=chunk_id,
                    source=source,
                    source_type=source_type,
                    document_name=doc_name or None,
                    page_number=page,
                    claim=claim,
                    verified=result.passed,
                    verification=result.to_dict(),
                )
            )
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
            given dimension (shared keyword check), so a passage with broad
            generic embedding similarity can never become a requirement
            citation for an unrelated dimension.
          - definitional/glossary exclusion: a definitions section ("terms
            used in this Act", a Definitions/Interpretation heading, or a
            numbered quoted-term list) is excluded entirely, before the
            semantic gates run.
          - mechanism requirement: a fallback citation must impose or name a
            governance mechanism (named body / reporting / enforcement /
            obligation language) — principle statements and definitional
            boilerplate are not requirement evidence.
          - substantive grounding: when semantic signal is available, the
            chunk must also be substantively about the dimension's
            operational content (SUBSTANTIVE_RELEVANCE_THRESHOLD).
        """
        # A no_citation entry is the model honestly declining to fabricate —
        # it should NOT satisfy the minimum-citation guarantee. Only real
        # citations (verified or not) do. When everything is a decline, replace
        # the placeholders with deterministic requirement citations instead.
        if any(not c.no_citation for c in citations):
            return citations
        # Substantive gate: built once per call, falls
        # back to keyword-only when no semantic machinery is available.
        subst_gate = None
        try:
            subst_gate = self._build_dimension_substantive_predicate(dimension)
        except Exception:
            subst_gate = None
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
            full_text = c.get("text") or ""
            # Definitional/glossary exclusion (cheap first pass, before the
            # semantic gates): a definitions section ranks on broad vocabulary
            # and can pass the keyword gate via a single defined term, yet
            # carries zero implementation content — never eligible.
            if _is_definitional_or_glossary(full_text):
                logger.info(
                    "definitional_section_skipped",
                    chunk_id=c.get("chunk_id", ""),
                    dimension=dimension,
                    source="deterministic_fallback",
                )
                continue
            text = full_text[:300]
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
            # Mechanism requirement: a fallback citation must impose or name a
            # governance mechanism. Honest absence is preferable to a weak
            # auto-attached citation.
            if not text_contains_mechanism(full_text):
                logger.info(
                    "fallback_no_mechanism_skipped",
                    chunk_id=c.get("chunk_id", ""),
                    dimension=dimension,
                    source="deterministic_fallback",
                )
                continue
            # Dimension grounding: only attach a chunk topically about THIS
            # dimension. An off-topic passage with broad embedding similarity
            # (e.g. a UN advisory-body participation paragraph) can never
            # become a requirement citation for an unrelated dimension.
            if dimension and not _chunk_matches_dimension(full_text, dimension):
                continue
            # Substantive grounding (anti-false-positive):
            # relevance is recall, substance is precision.
            if dimension and subst_gate is not None and not subst_gate(full_text, dimension):
                logger.info(
                    "fallback_not_substantive_skipped",
                    chunk_id=c.get("chunk_id", ""),
                    dimension=dimension,
                    source="deterministic_fallback",
                )
                continue
            # Deterministically attached requirement citation. The quote IS the
            # chunk's own text, so a normal verify would trivially pass and show
            # a misleading green badge — mark it as auto-attached instead.
            result.append(
                ModuleCitation(
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
                        "failure_reason": (
                            "Added as the most relevant passage for this requirement; "
                            "the analysis did not quote it itself."
                        ),
                    },
                )
            )
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
        skipped, definitional/glossary sections are excluded, a chunk must
        impose or name a governance mechanism, and only dimension-topical
        chunks that also pass the substantive-specificity gate are attached
        (marked auto-attached, never "verified").

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
                    if dimension and text and not _chunk_matches_dimension(text, dimension):
                        logger.info(
                            "module3_citation_off_topic_dropped",
                            chunk_id=c.chunk_id,
                            dimension=dimension,
                        )
                        continue
            kept.append(c)
            real_kept += 1

        # Substantive gate: built once per call, falls
        # back to keyword-only when no semantic machinery is available.
        subst_gate = None
        try:
            subst_gate = self._build_dimension_substantive_predicate(dimension)
        except Exception:
            subst_gate = None
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
            # Definitional/glossary exclusion (cheap first pass, before the
            # semantic gates): a definitions section ("Terms used in this Act
            # are as follows...") ranks on broad vocabulary and passes the
            # keyword gate via a single defined term, yet carries zero
            # implementation content — never eligible as an implementation
            # citation.
            if _is_definitional_or_glossary(full_text):
                logger.info(
                    "definitional_section_skipped",
                    chunk_id=cid,
                    dimension=dimension,
                    source="deterministic_fallback",
                )
                continue
            # TOC/preamble guard: a table-of-contents or cover-page fragment
            # ranks on broad vocabulary but carries no evidence content.
            # Deliberately narrow — "Executive Summary" is NOT excluded, since
            # a substantive summary section can carry the dimension's key
            # commitments and is legitimately citable.
            head = full_text[:200].lower()
            if "table of contents" in head or head.lstrip().startswith("title page"):
                continue
            # Mechanism requirement: an implementation citation must impose or
            # name a governance mechanism. Principle statements and
            # definitional boilerplate are not implementation evidence; honest
            # absence beats a weak auto-attached citation.
            if not text_contains_mechanism(full_text):
                logger.info(
                    "fallback_no_mechanism_skipped",
                    chunk_id=cid,
                    dimension=dimension,
                    source="deterministic_fallback",
                )
                continue
            # Dimension grounding: only attach chunks topically about THIS
            # dimension (checked on the full truncated text, not the quote).
            if dimension and not _chunk_matches_dimension(full_text, dimension):
                continue
            # Substantive grounding: the chunk must
            # be substantively about the dimension's operational content, not
            # merely keyword-topical.
            if dimension and subst_gate is not None and not subst_gate(full_text, dimension):
                logger.info(
                    "fallback_not_substantive_skipped",
                    chunk_id=cid,
                    dimension=dimension,
                    source="deterministic_fallback",
                )
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
            kept.append(
                ModuleCitation(
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
                            "Added as the document's most relevant passage for this "
                            "dimension; the analysis did not quote it itself."
                        ),
                    },
                )
            )
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
            evidence_list.append(
                RetrievedEvidence(
                    chunk_id=cit.chunk_id,
                    text=cit.quote[:500],
                    page_number=cit.page_number,
                    source_framework=cit.source,
                    document_name=getattr(cit, "document_name", None),
                    similarity_score=similarity_map.get(cit.chunk_id),
                    verified=cit.verified,
                    verification=cit.verification,
                )
            )
        return evidence_list

    def _compute_evidence_agreement_pairs(self, citations: list[ModuleCitation]) -> list:
        """Real evidence-agreement pairs for the confidence calculation —
        replaces the flat 0.5 placeholder confidence used to fall back to
        when no pairs were computed at all. Cheap and local (embeddings
        only, no LLM call): builds EvidenceItem objects from the same
        citations already gathered for this dimension and pairwise-compares
        them via analyze_evidence_agreement."""
        items: list[EvidenceItem] = []
        seen: set[str] = set()
        for cit in citations:
            if not cit.chunk_id or cit.chunk_id in seen or not cit.quote:
                continue
            seen.add(cit.chunk_id)
            items.append(
                EvidenceItem(
                    chunk_id=cit.chunk_id,
                    text=cit.quote,
                    source_framework=cit.source,
                    is_document=(cit.source_type == "document"),
                )
            )
        if len(items) < 2:
            return []
        try:
            return analyze_evidence_agreement(
                items, batch_embed_function=self.vector_store.embedding_service.embed
            )
        except Exception as exc:
            logger.warning("evidence_agreement_pairs_failed", error=str(exc))
            return []

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
        fw_label = ", ".join(fw_names) if fw_names else "the international frameworks assessed"

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

    def _build_dimension_substantive_predicate(
        self,
        dimension: str,
        shared_cache: dict[str, list[float]] | None = None,
    ) -> Callable[[str, str], bool] | None:
        """Anti-false-positive gate: is the chunk SUBSTANTIVELY about the
        dimension's operational content, or merely topically related?

        Keyword relevance (_chunk_matches_dimension) is the RECALL gate, and
        it admits PROCEDURAL authority provisions too — "the Minister may
        approve/support AI data centres" is topically adjacent to
        Environmental Sustainability (data centres consume energy) but
        imposes no environmental governance requirement, so it must not be
        attached as evidence for it. This predicate is the PRECISION gate: a chunk is
        substantive only when its mechanism-bearing sentences are
        semantically close to the dimension's profile (definition +
        aspects) above SUBSTANTIVE_RELEVANCE_THRESHOLD. Procedural
        authority alone never crosses that bar.

        Returns None when no semantic signal is available (no embedder or
        no profile), in which case callers fall back to keyword relevance
        (no stricter bar) rather than blocking on missing machinery.
        """
        embed_fn = getattr(self.vector_store, "embed_query", None)
        profile_texts: list[str] = []
        try:
            profiles = self.retrieval_pipeline.get_or_build_profiles()
            profile = profiles.get(dimension)
            if profile is not None:
                profile_texts = [profile.definition] + list(profile.aspects)
        except Exception:
            profile_texts = []
        profile_embs: list[list[float]] = []
        if embed_fn is not None:
            batch_embed = getattr(self.vector_store.embedding_service, "embed", None)
            try:
                profile_embs = (
                    list(batch_embed(profile_texts))
                    if batch_embed and profile_texts
                    else [embed_fn(pt) for pt in profile_texts]
                )
            except Exception:
                profile_embs = []
        if not profile_embs or embed_fn is None:
            return None
        # See _build_dimension_relevance_predicate — same shared, pre-warmed
        # cache, so a sentence both gates need is embedded once, not twice.
        cache: dict[str, list[float]] = shared_cache if shared_cache is not None else {}

        def match(text: str, dim: str) -> bool:
            sentences = _mechanism_sentences(text)
            if not sentences:
                return False
            for s in sentences:
                emb = cache.get(s)
                if emb is None:
                    try:
                        emb = embed_fn(s)
                    except Exception:
                        continue
                    cache[s] = emb
                if max(_cosine_sim(emb, pe) for pe in profile_embs) >= (
                    SUBSTANTIVE_RELEVANCE_THRESHOLD
                ):
                    return True
            return False

        return match

    def _dimension_enforcement_backing(
        self,
        scoring_pool: list[dict[str, Any]],
        dimension: str,
        workspace_id: str,
        country: str,
    ) -> bool:
        """v2: can THIS dimension claim the instrument's enforcement machinery?

        Only when a document that has its own enforcement regime also supplies
        at least one binding sentence to this dimension. v1 asked whether ANY
        document in the workspace had a regime, which let Japan's 2003 privacy
        statute back Transparency and Fairness.
        """
        from src.grading import dimension_enforcement_backing

        regimes = self._document_regimes(workspace_id)
        if not regimes:
            return False
        by_doc: dict[str, list[str]] = {}
        for chunk in scoring_pool:
            if not isinstance(chunk, dict):
                continue
            md = chunk.get("metadata") or {}
            doc = md.get("document_name") or chunk.get("document_name") or "?"
            for sent in _split_sentences(chunk.get("text") or ""):
                sent = " ".join(sent.split())
                if 40 <= len(sent) <= 600 and _sentence_has_core_term(sent, dimension):
                    by_doc.setdefault(doc, []).append(sent)
        return dimension_enforcement_backing(by_doc, regimes, dimension, country)

    def _workspace_documents(self, workspace_id: str) -> dict[str, list[str]]:
        """Every chunk in the workspace, grouped by the document it came from.

        Cached: the provision profile reads it once per dimension, and each
        read was a full fetch of the workspace from the store — eight
        identical fetches a run, over a thousand chunks each on the UK.
        """
        cache = getattr(self, "_workspace_documents_cache", None)
        if cache is None:
            cache = {}
            self._workspace_documents_cache = cache
        if workspace_id in cache:
            return cache[workspace_id]
        by_doc: dict[str, list[str]] = {}
        try:
            pipeline = getattr(self, "retrieval_pipeline", None)
            store = getattr(pipeline, "vectorstore", None) if pipeline else None
            if store is None:
                return by_doc
            raw = store.collection.get(
                where={"workspace_id": workspace_id},
                include=["documents", "metadatas"],
            )
            for text, md in zip(raw.get("documents") or [], raw.get("metadatas") or []):
                name = (md or {}).get("document_name") or "?"
                by_doc.setdefault(name, []).append(text or "")
        except Exception as exc:
            logger.warning("workspace_documents_failed", workspace_id=workspace_id, error=str(exc))
            return by_doc
        cache[workspace_id] = by_doc
        return by_doc

    def _document_regimes(self, workspace_id: str) -> set[str]:
        """Names of workspace documents that establish enforcement machinery."""
        from src.grading import detect_enforcement_regime

        cache = getattr(self, "_doc_regime_cache", None)
        if cache is None:
            cache = {}
            self._doc_regime_cache = cache
        if workspace_id in cache:
            return cache[workspace_id]
        found = {
            name
            for name, texts in self._workspace_documents(workspace_id).items()
            if detect_enforcement_regime(texts)
        }
        cache[workspace_id] = found
        logger.info("document_regimes", workspace_id=workspace_id, documents=sorted(found))
        return found

    def _voluntary_documents(self, workspace_id: str) -> set[str]:
        """Names of workspace documents that declare themselves non-binding.

        Asked of each document whole rather than of a dimension's retrieval
        pool. The pool mixes documents, so a workspace holding both a statute
        and a set of guidelines got one answer for both — and got it per
        dimension, so the same document could be voluntary for Safety and
        binding for Privacy.
        """
        cache = getattr(self, "_doc_voluntary_cache", None)
        if cache is None:
            cache = {}
            self._doc_voluntary_cache = cache
        if workspace_id in cache:
            return cache[workspace_id]
        found = {
            name
            for name, texts in self._workspace_documents(workspace_id).items()
            if detect_nonbinding_document(texts)
        }
        cache[workspace_id] = found
        logger.info("voluntary_documents", workspace_id=workspace_id, documents=sorted(found))
        return found

    def _scoring_pools(self, workspace_id: str) -> dict[str, list[dict[str, Any]]]:
        """The ranked scoring pool for each dimension, retrieved once.

        The verdict path needs a pool twice — once for the rank the structural
        admission depends on, once for the enforcement backing — and the two
        must be the same pool, so it is fetched here and read from the cache.
        """
        cache = getattr(self, "_scoring_pool_cache", None)
        if cache is None:
            cache = {}
            self._scoring_pool_cache = cache
        if workspace_id in cache:
            return cache[workspace_id]
        pools: dict[str, list[dict[str, Any]]] = {}
        for dimension in GOVERNANCE_DIMENSIONS:
            try:
                pools[dimension] = self.retrieval_pipeline.retrieve_scoring_pool(
                    dimension=dimension, workspace_id=workspace_id
                )
            except Exception as exc:
                logger.warning("dimension_scoring_pool_failed", dimension=dimension, error=str(exc))
                pools[dimension] = []
        cache[workspace_id] = pools
        return pools

    def _structural_candidates(self, workspace_id: str) -> dict[str, list[tuple[str, str]]]:
        """Provisions admitted on structure rather than vocabulary, per dimension.

        Returned with the document each came from, so they are capped by their
        own source like every other provision.

        Computed for all eight dimensions at once because the specificity
        guard is cross-dimensional: it drops a provision that qualifies for
        too many dimensions, which cannot be decided while looking at one.
        """
        from src.grading import (
            apply_specificity_guard,
            recital_boundary,
            sentence_function,
            structurally_relevant,
        )

        cache = getattr(self, "_structural_cache", None)
        if cache is None:
            cache = {}
            self._structural_cache = cache
        if workspace_id in cache:
            return cache[workspace_id]

        boundaries: dict[str, int | None] = {}
        candidates: dict[str, list[tuple[str, str]]] = {}
        for dimension, pool in self._scoring_pools(workspace_id).items():
            found: list[tuple[str, str]] = []
            for rank, chunk in enumerate(pool):
                if not isinstance(chunk, dict):
                    continue
                md = chunk.get("metadata") or {}
                document = md.get("document_name") or "?"
                if document not in boundaries:
                    boundaries[document] = recital_boundary(
                        [
                            c
                            for c in pool
                            if (c.get("metadata") or {}).get("document_name") == document
                        ]
                    )
                cut = boundaries.get(document)
                page = md.get("page_number") or 0
                in_recital = bool(cut and page and page < cut)
                for sent in _split_sentences(chunk.get("text") or ""):
                    sent = " ".join(sent.split())
                    if not 40 <= len(sent) <= 600:
                        continue
                    if sentence_function(sent, is_recital=in_recital) != "operative":
                        continue
                    if _sentence_has_core_term(sent, dimension):
                        continue
                    if not structurally_relevant(sent, rank):
                        continue
                    # Structural admission has no topic signal of its own — it
                    # trusts the retriever's ranking, a regulated party and a
                    # hard modal. So a provision that names ANOTHER dimension
                    # explicitly, and this one not at all, belongs there rather
                    # than here: six DPDP Act privacy duties ("shall erase
                    # personal data", "shall give the Board intimation of a
                    # breach") were India's Safety evidence on exactly this
                    # path. 38% of structurally-admitted provisions carry that
                    # contradiction, and the evidence to reject them is already
                    # on the sentence.
                    if any(
                        other != dimension and _sentence_has_core_term(sent, other)
                        for other in GOVERNANCE_DIMENSIONS
                    ):
                        continue
                    found.append((sent, document))
            candidates[dimension] = found
        texts_only = {d: [t for t, _ in v] for d, v in candidates.items()}
        kept = {d: set(v) for d, v in apply_specificity_guard(texts_only).items()}
        guarded = {
            d: [pair for pair in v if pair[0] in kept.get(d, ())] for d, v in candidates.items()
        }
        cache[workspace_id] = guarded
        logger.info(
            "structural_candidates",
            workspace_id=workspace_id,
            counts={d: len(v) for d, v in guarded.items()},
        )
        return guarded

    def _dimension_profile(self, workspace_id: str, country: str, dimension: str) -> Any:
        """The scored provision profile for one dimension, computed once.

        Factored out of _compute_deterministic_verdict so the batched
        mechanism adjudicator can prepare all eight dimensions before making a
        single call, instead of each dimension asking for itself.

        Core-term evidence is swept from the WHOLE workspace, not from the
        ranked pool. The pool is capped at a fixed number of chunks, so the
        share of a document the scorer sees falls as the document grows:
        measured against every admissible binding provision in the corpus, the
        pool carried 100% of China's and 17% of the United Kingdom's. That is
        the document-length artifact retrieve_scoring_pool was written to
        remove, surviving at a larger cap. Pattern scoring costs nothing per
        chunk, so for this path there is no reason to rank.
        """
        cache = getattr(self, "_dimension_profile_cache", None)
        if cache is None:
            cache = {}
            self._dimension_profile_cache = cache
        key = (workspace_id, country or "", dimension)
        if key in cache:
            return cache[key]

        voluntary = self._voluntary_documents(workspace_id)
        with_regime = self._document_regimes(workspace_id)

        def _cap(document: str) -> str:
            if document in voluntary:
                return SOURCE_VOLUNTARY
            return "" if document in with_regime else SOURCE_UNENFORCED

        sentences: list[str] = []
        source_force: dict[str, str] = {}
        for document, texts in self._workspace_documents(workspace_id).items():
            cap = _cap(document)
            for text in texts:
                for sent in _split_sentences(text or ""):
                    sent = " ".join(sent.split())
                    if not 40 <= len(sent) <= 600:
                        continue
                    if sentence_function(sent) != "operative":
                        continue
                    if _sentence_has_core_term(sent, dimension):
                        sentences.append(sent)
                        source_force[sent] = cap

        # Provisions that carry a duty for this dimension in the country's own
        # vocabulary, which the core-term table cannot anticipate.
        for sent, document in self._structural_candidates(workspace_id).get(dimension, []):
            if sent not in source_force:
                sentences.append(sent)
                source_force[sent] = _cap(document)

        profile = build_provision_profile(
            sentences,
            dimension=dimension,
            own_jurisdiction=country or "",
            source_force=source_force,
        )
        cache[key] = profile
        return profile

    def _adjudicated_mechanisms(self, workspace_id: str, country: str) -> dict[str, Any]:
        """Every dimension's adjudicated mechanisms, from ONE model call.

        Asking per dimension cost eight calls per country. Measured, that 50%
        rise in request count took the daily ceiling from roughly five
        countries to three and killed a run mid-batch — the free-tier quota
        counts REQUESTS, so batching is the only lever that helps.

        Cached per workspace: the first dimension to ask pays for all eight,
        every other dimension reads the result.
        """
        # Dimensions run in a thread pool, so without a lock the first three
        # workers all find an empty cache and each fire the batch call —
        # turning the one-call saving back into three. Double-checked inside
        # the lock so the winner pays and the rest read the result.
        cache = getattr(self, "_adjudication_cache", None)
        if cache is None:
            cache = {}
            self._adjudication_cache = cache
        lock = getattr(self, "_adjudication_lock", None)
        if lock is None:
            lock = threading.Lock()
            self._adjudication_lock = lock
        if workspace_id in cache:
            return cache[workspace_id]
        with lock:
            if workspace_id in cache:
                return cache[workspace_id]

            cue_results: dict[str, Any] = {}
            requests: dict[str, tuple[Any, list[Any]]] = {}
            for dim in GOVERNANCE_DIMENSIONS:
                try:
                    profile = self._dimension_profile(workspace_id, country, dim)
                    if profile is None or profile.n_scored == 0:
                        continue
                    cue = detect_mechanisms(profile.sentences, dim)
                    if cue is None:
                        continue
                    cue_results[dim] = cue
                    # Only dimensions with something matched are worth asking
                    # about; one with nothing present still needs to be returned,
                    # because its absent list is what the gaps panel reads.
                    if getattr(cue, "present", None):
                        requests[dim] = (cue, profile.sentences)
                except Exception as exc:
                    logger.warning("adjudication_prepare_failed", dimension=dim, error=str(exc))
            if requests:
                cue_results.update(adjudicate_batch(requests, self.provider))
                # A model call that feeds the verdict belongs in the run's call
                # count and its provenance, whether it succeeded or not.
                if any(getattr(c, "adjudication", "") for c in cue_results.values()):
                    self._adjudication_calls = getattr(self, "_adjudication_calls", 0) + 1
            cache[workspace_id] = cue_results
            return cue_results

    def _prepare_workspace(self, workspace_id: str, country: str) -> None:
        """Everything the eight verdicts share, computed once, before any runs.

        The shared preparation — scoring pools, structural candidates, the
        eight provision profiles, the mechanism pass — is cached per
        workspace, and each piece used to be filled by whichever dimension
        asked first. Three worker threads started together, all found the
        cache empty, and all built every piece in parallel: three copies of
        regex-heavy work contending for the interpreter lock. Measured on one
        thread the whole preparation takes 6-23 seconds a country; under that
        contention it was a large share of runs lasting five to eleven
        minutes. Same functions, same inputs, same caches — built once, in
        order, so every verdict is unchanged.

        Failures are left for the dimension that needs the piece, which
        raises them where it always did.
        """
        if not workspace_id or getattr(self, "retrieval_pipeline", None) is None:
            return
        try:
            self._scoring_pools(workspace_id)
            self._structural_candidates(workspace_id)
            for dimension in GOVERNANCE_DIMENSIONS:
                self._dimension_profile(workspace_id, country, dimension)
            self._adjudicated_mechanisms(workspace_id, country)
        except Exception as exc:
            logger.warning(
                "workspace_preparation_failed", workspace_id=workspace_id, error=str(exc)
            )

    def _compute_deterministic_verdict(
        self,
        dimension: str,
        workspace_id: str,
        country: str,
    ) -> dict[str, Any] | None:
        """Coverage, depth and mechanism breakdown — BEFORE any LLM call.

        This runs first so the verdict can be handed to the model as an INPUT
        rather than being computed afterwards and overriding whatever the model
        already wrote. That ordering is the fix for an entire class of
        contradiction found in QA: the model used to form its own verdict,
        write prose justifying it, and then have the verdict replaced —
        leaving "the document does not establish X" sitting underneath a
        Covered result, and recommendations aimed at a different conclusion
        than the one reported.

        NO LONGER LLM-FREE, and the name now overstates the case. Coverage,
        depth, the tier ladder and every gate are still pure code on the
        document's own text. But mechanism PRESENCE now passes through
        `adjudicate_mechanisms`, which asks a model whether the provision a
        cue matched actually establishes the mechanism — because the cue
        selector was measured at 20% precision on the bound counts this gate
        reads, and a mechanism wrongly marked present is a gap that never
        reaches the reader.

        What that costs: the verdict is reproducible rather than deterministic
        by construction. The call is seeded, so the same document returns the
        same answer, and any failure falls back to the cue result — but it is
        a model in the path and the docs should not pretend otherwise.

        What it does NOT cost: the model never sees or sets a tier, never
        touches a threshold, and cannot move a verdict upward. The gate it
        feeds is downgrade-only, so the worst a wrong adjudication can do is
        withhold depth the cue pass would have granted on a bad match.
        """
        if not workspace_id or getattr(self, "retrieval_pipeline", None) is None:
            return None
        # The ranked pool only feeds structural admission and enforcement
        # backing; an empty one is not a reason to stop.
        scoring_pool = self._scoring_pools(workspace_id).get(dimension) or []

        profile = self._dimension_profile(workspace_id, country, dimension)
        if profile is None:
            return None
        # A profile that scored nothing is still a verdict: every sentence of
        # every supplied document was read and none addresses the dimension,
        # which coverage_from_profile and depth_from_profile report as Missing
        # and Unaddressed. Returning None here used to hand the verdict to the
        # model's own label instead.

        # Mechanisms come from the workspace-wide pass, which holds the ONLY
        # detect_mechanisms call site. Cues are generous on purpose, so 4 of
        # every 5 matches point at a provision that merely contains the
        # keyword; the pass adjudicates them and falls back to the raw cue
        # result on any failure.
        try:
            mechanisms = self._adjudicated_mechanisms(workspace_id, country).get(dimension)
        except Exception:
            mechanisms = None
        # Mechanism breadth gates the Covered tier downward only — see
        # coverage_from_profile.
        cov_label, cov_note = coverage_from_profile(profile, mechanisms=mechanisms)
        # Enforcement backing is scoped to the document that actually carries
        # this dimension's duties. Pooling the workspace let a privacy statute
        # lend its penalties to every other dimension.
        backing = self._dimension_enforcement_backing(
            scoring_pool, dimension, workspace_id, country or ""
        )
        mat_label, mat_note = depth_from_profile(profile, document_enforcement_regime=backing)
        # A dimension cannot be operating while none of the mechanisms it
        # needs is carried by a duty. Holds the stage down, never up.
        bound = sum(
            1
            for tier in (mechanisms.present if mechanisms else {}).values()
            if tier >= TIER_OBLIGATORY
        )
        mat_label, gate_note = apply_mechanism_gate(mat_label, bound)
        if gate_note:
            mat_note = gate_note

        return {
            "profile": profile,
            "scoring_pool": scoring_pool,
            "coverage_label": cov_label,
            "coverage_note": cov_note,
            "depth_label": mat_label,
            "depth_note": mat_note,
            "mechanisms": mechanisms,
        }

    def _analyze_dimension_combined(
        self,
        dimension: str,
        retrieval: ModuleRetrievalResult,
        debug_ctx: dict[str, Any] | None = None,
        country: str = "",
        workspace_id: str = "",
    ) -> GovernanceGap:
        call = self._prepare_dimension_combined(dimension, retrieval, country, workspace_id)
        combined = generate_with_retry(
            provider=self.provider,
            prompt=call.prompt,
            schema=self._get_combined_module_schema(),
            system_prompt=call.system_prompt,
            operation=f"module1_2_{dimension.lower().replace(' ', '_')}",
            debug_ctx=debug_ctx,
        )
        return self._finish_dimension_combined(call, combined)

    def _prepare_dimension_combined(
        self,
        dimension: str,
        retrieval: ModuleRetrievalResult,
        country: str = "",
        workspace_id: str = "",
    ) -> _DimensionCall:
        """Everything before the Module 1+2 model call: the verdict and the prompt."""
        dimension_def = analysis_prompts.build_dimension_definition_block(dimension)

        # Decide the verdict FIRST, deterministically, then hand it to the
        # model to explain. See _compute_deterministic_verdict for why this
        # ordering matters.
        determined = self._compute_deterministic_verdict(
            dimension=dimension, workspace_id=workspace_id, country=country
        )
        if determined is None:
            # Not assessed rather than guessed: without the evidence profile
            # there is no verdict to explain, and the model is never asked for
            # one. Raised before the call, so no quota is spent on it.
            raise RuntimeError(
                f"The evidence profile for {dimension} could not be computed, so the "
                "dimension was not scored."
            )
        mech = determined.get("mechanisms")
        prof = determined["profile"]
        verdict_block: dict[str, Any] = {
            "coverage_label": determined["coverage_label"],
            "depth_label": determined["depth_label"],
            "basis": determined["coverage_note"],
            "missing_mechanisms": list(mech.absent)[:6] if mech else [],
            "present_mechanisms": list(mech.present)[:6] if mech else [],
            # Instrument character, measured from the document itself.
            # Without it the model narrated a self-declared voluntary
            # instrument as if it imposed duties — "the document mandates
            # that AI business actors deploy privacy protection
            # mechanisms" for a soft-law guideline with zero
            # enforcement-tier provisions, in 7 of 8 dimensions.
            "binding_provisions": prof.n_binding,
            "enforceable_provisions": prof.n_enforceable,
        }

        # How THIS document numbers its own divisions, read off the document
        # rather than assumed. Detected from the scoring pool (the widest
        # document sample already in hand, so no extra retrieval) and falling
        # back to the prompt's document chunks.
        division_vocabulary: list[str] = []
        try:
            _pool = determined.get("scoring_pool") or retrieval.document_chunks or []
            _vocab_source = [(c.get("text") or "") for c in _pool if isinstance(c, dict)]
            division_vocabulary = detect_division_vocabulary(_vocab_source)
        except Exception as exc:
            logger.warning("division_vocabulary_failed", dimension=dimension, error=str(exc))

        sys_prompt, prompt = analysis_prompts.build_module1_2_combined_prompt(
            dimension=dimension,
            dimension_definition=dimension_def,
            document_chunks=retrieval.document_chunks,
            module1_chunks=retrieval.module1_chunks,
            module2_chunks=retrieval.module2_chunks,
            country=country,
            determined_verdict=verdict_block,
            division_vocabulary=division_vocabulary,
        )
        return _DimensionCall(
            dimension=dimension,
            retrieval=retrieval,
            determined=determined,
            workspace_id=workspace_id,
            dimension_definition=dimension_def,
            system_prompt=sys_prompt,
            prompt=prompt,
        )

    def _finish_dimension_combined(self, call: _DimensionCall, combined: Any) -> GovernanceGap:
        """Everything after the Module 1+2 model call, for one dimension's answer.

        Identical whether the answer came from a call of its own or from one
        entry of the batched call, which is what keeps batching from changing
        anything downstream of the model.
        """
        dimension = call.dimension
        retrieval = call.retrieval
        determined = call.determined
        workspace_id = call.workspace_id

        # ── Normalize Module 1 fields ───────────────────────────────────
        # The model's own label, kept only to log when it disagrees with the
        # computed verdict it was asked to explain.
        coverage_str = (
            str(getattr(combined, "coverage", "Partial") or "Partial").strip().capitalize()
        )
        if coverage_str not in ("Covered", "Partial", "Missing"):
            coverage_str = "Partial"
        model_coverage = CoverageLevel(coverage_str)

        reason_flagged = str(getattr(combined, "reason_flagged", "") or "")
        verdict_challenge = str(getattr(combined, "verdict_challenge", "") or "").strip()
        if verdict_challenge:
            logger.warning(
                "model_challenged_computed_verdict",
                dimension=dimension,
                computed_coverage=(determined or {}).get("coverage_label"),
                challenge=verdict_challenge[:300],
            )
        # Scrubbed here, at the single point the narrative enters the pipeline,
        # so every downstream consumer (verdict prose, gap analysis, brief) is
        # covered by one call rather than each remembering to sanitise.
        coverage_reasoning = strip_chunk_id_citations(
            str(getattr(combined, "coverage_reasoning", "") or "")
        )
        coverage_example = strip_chunk_id_citations(
            str(getattr(combined, "coverage_example", "") or "")
        )
        principle_ack = bool(getattr(combined, "principle_acknowledged", True))
        mechanisms = [m for m in (getattr(combined, "operational_mechanisms", []) or []) if m]

        # ── The verdict: read back, never recomputed, never the model's ──
        # Coverage, depth and mechanism breadth were computed once, in
        # _compute_deterministic_verdict, BEFORE the model call, and the model
        # was shown them as fixed inputs to explain. This block reads that
        # result back; it does not recompute it (test_verdict_single_source).
        #
        # A second path used to live here for when no evidence profile existed:
        # it took the MODEL's own coverage label and ran the old keyword ladder
        # over it, and the ladder could raise the verdict — to Covered, on
        # mechanisms the model itself had reported. No stored run ever took it,
        # but while it existed "the model never decides" held only on the main
        # path. A dimension whose profile scored nothing is now a deterministic
        # Missing (see _compute_deterministic_verdict), and one whose profile
        # could not be computed is not assessed at all.
        if determined is None:
            raise RuntimeError(f"No evidence profile for {dimension}; it cannot be scored.")
        strength_profile = determined["profile"]
        scoring_pool = determined["scoring_pool"]
        mech = determined.get("mechanisms")
        _cov_label = determined["coverage_label"]
        coverage = {
            "Covered": CoverageLevel.COVERED,
            "Partial": CoverageLevel.PARTIAL,
            "Missing": CoverageLevel.MISSING,
        }[_cov_label]
        if coverage != model_coverage:
            # The model is told the verdict and asked not to re-judge it; a
            # different label here is telemetry about the prompt, nothing more.
            logger.info(
                "model_label_differs_from_verdict",
                dimension=dimension,
                verdict=_cov_label,
                model_label=model_coverage.value,
                scored=strength_profile.n_scored,
                binding=strength_profile.n_binding,
                enforceable=strength_profile.n_enforceable,
            )
        profile_coverage_note = determined["coverage_note"]
        # Mechanism breakdown: WHICH of the governance mechanisms the
        # reference frameworks expect for this dimension the document
        # actually provides, and how many as a binding duty rather than a
        # mention. This is where the ingested corpus informs the report — it
        # names the specific gaps behind a verdict instead of leaving
        # "Partial" unexplained.
        if mech is not None:
            mech_note = mech.summary()
            if mech_note:
                profile_coverage_note = (
                    profile_coverage_note + " " + mech_note if profile_coverage_note else mech_note
                )
                logger.info(
                    "mechanism_coverage_computed",
                    dimension=dimension,
                    present=mech.met,
                    total=mech.total,
                    binding=mech.binding_met,
                    coverage=_cov_label,
                )
        # The profile's own rationale is written for a policy reader and states
        # what the document actually contains ("imposes binding requirements…
        # 3 backed by enforcement"), so it is the user-facing explanation.
        if profile_coverage_note:
            coverage_reasoning = (
                coverage_reasoning + " " if coverage_reasoning else ""
            ) + profile_coverage_note

        # ── Covered verdicts never ship under gap prose ──────────────
        # reason_flagged is the model's answer to "what is missing here?", and
        # it is written BEFORE the deterministic verdict is applied. When the
        # verdict lands on Covered, that text contradicts the label outright:
        # live runs shipped Covered for Inclusivity above "lacks technical
        # mechanisms for algorithmic bias testing, accessibility standards, or
        # demographic fairness monitoring".
        #
        # A reconciliation for this existed, but it sat behind a flag the
        # winning code path cleared, so it never ran on a real verdict. It is
        # unconditional: the question "does this text contradict the verdict?"
        # has nothing to do with how the verdict was produced.
        #
        # The specific mechanism gaps are NOT lost — coverage_reasoning still
        # carries "Provides N of M governance mechanisms ... Not addressed:
        # ...", which states them as a breadth measurement rather than as a
        # finding that contradicts the label.
        if coverage == CoverageLevel.COVERED and reason_flagged.strip():
            _rf_score, _rf_phrases = detect_gap_assertions(reason_flagged)
            if _rf_score >= GAP_ASSERTION_THRESHOLD:
                logger.info(
                    "covered_reason_flagged_reconciled",
                    dimension=dimension,
                    phrases=_rf_phrases,
                    original=reason_flagged[:200],
                )
                reason_flagged = (
                    "No critical gap — the document governs this dimension "
                    "through its own binding provisions. Remaining mechanism "
                    "gaps are described in the coverage reasoning."
                )

        # gap_detected follows the computed coverage, not the LLM's label.
        gap_detected = coverage != CoverageLevel.COVERED

        # ── Covered-tier coverage_example backfill (deterministic) ────
        # The model is asked for coverage_example only when it judges the
        # dimension Covered, and it does not always agree with the computed
        # verdict it was handed. A Covered card must not ship with a blank
        # example, so one is built from the document's own operational
        # mechanisms (the same fallback chain as
        # _build_covered_synthesis_fallback). An example the model DID
        # produce is always kept.
        if coverage == CoverageLevel.COVERED and not coverage_example.strip() and mechanisms:
            coverage_example = "The document establishes operational mechanisms: " + "; ".join(
                mechanisms[:3]
            )
            logger.info(
                "covered_coverage_example_backfilled",
                dimension=dimension,
                num_mechanisms=len(mechanisms),
            )

        # ── Implementation depth: read back, like coverage ──────────────
        # Same profile, same force bar, a different question: how far the
        # governance has been built out (intent → institution → duty →
        # enforcement), not whether the dimension is governed at all. So a
        # document can be broadly Covered yet only Emerging, or narrowly
        # Partial yet Operationalized.
        depth_reasoning = determined["depth_note"]
        depth = {
            "Institutionalized": ImplementationDepth.ESTABLISHED,
            "Operationalized": ImplementationDepth.DEVELOPING,
            "Delegated": ImplementationDepth.DELEGATED,
            "Emerging": ImplementationDepth.EMERGING,
            "Unaddressed": ImplementationDepth.UNADDRESSED,
        }[determined["depth_label"]]

        # Validate the article/recital/section NUMBERS written into the
        # narrative against the source text actually retrieved. Chunk-level
        # verification proves a cited chunk exists; it does not catch a
        # plausible-but-invented number attached to a real obligation, which
        # measurement showed to be the most common residual error.
        _unverifiable_citations: list[str] = []
        _fabricated_citations: list[str] = []
        try:
            _corpus = " ".join(
                (c.get("text") or "") for c in (scoring_pool or []) if isinstance(c, dict)
            )
            if _corpus:
                # Compare against the WHOLE uploaded document as well, not just
                # the passages retrieved for this dimension. A number the model
                # invented and a real provision it recalled from memory are
                # different failures and deserve different severity — see
                # classify_narrative_citations.
                # Per document, not one joined blob — each instrument's own
                # division numbering has to stay separate or a long statute
                # lends its ordinals to a short guidance note.
                _document_text: list[str] = []
                try:
                    if workspace_id and getattr(self, "retrieval_pipeline", None):
                        _document_text = self.retrieval_pipeline._workspace_document_texts(
                            workspace_id
                        )
                except Exception:
                    # Cached, cheap and optional: losing it costs severity
                    # detail, never the flag itself.
                    _document_text = []

                _split = classify_narrative_citations(
                    [coverage_reasoning, reason_flagged, coverage_example],
                    _corpus,
                    _document_text,
                )
                _fabricated_citations = _split["fabricated"]
                _unverifiable_citations = _split["unsupported"]
                if _fabricated_citations:
                    logger.error(
                        "narrative_citations_fabricated",
                        dimension=dimension,
                        citations=_fabricated_citations,
                    )
                if _unverifiable_citations:
                    logger.warning(
                        "narrative_citations_unsupported",
                        dimension=dimension,
                        citations=_unverifiable_citations,
                    )
        except Exception as exc:
            logger.warning(
                "citation_number_validation_failed",
                dimension=dimension,
                error=str(exc),
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
            p
            for p in [
                f"Consensus: {fs_consensus}" if fs_consensus else "",
                f"Differences: {fs_differences}" if fs_differences else "",
                f"Overall assessment: {fs_overall}" if fs_overall else "",
            ]
            if p
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
            # When the model answered in the Partial/Missing shape (Branch B)
            # although the computed verdict is Covered, this field comes back
            # empty. Backfill from the recommendations it DID write instead
            # of shipping an empty section: they are already
            # document-grounded (name the same real mechanism/institution
            # per the prompt's rules), just phrased as a fix rather than a
            # refinement — a light touch-up reframes the verb, nothing else
            # is invented.
            strengthening = future_strengthening_opportunities[:3]
            if not strengthening and llm_recommendations:
                strengthening = [
                    re.sub(
                        r"^(should|must|needs? to|is required to|are required to)\s+",
                        "may further ",
                        r,
                        count=1,
                        flags=re.IGNORECASE,
                    )
                    for r in llm_recommendations[:3]
                ]
            best_practices = BestPractices(
                opening=BEST_PRACTICES_OPENING,
                future_strengthening_opportunities=strengthening,
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
        # Drift detection scans ONLY the overall_assessment part of a Covered
        # synthesis (the compliance justification) — the Consensus / Differences
        # sections describe the external frameworks, where words like "lacks"
        # or "requires" legitimately describe framework positions, not the
        # policy. Gap-filling language in the overall assessment is the true
        # tier/content drift signal.
        drift_text = fs_overall or framework_synthesis
        if coverage == CoverageLevel.COVERED and drift_text:
            drift_score, drift_phrases = detect_covered_synthesis_drift(drift_text)
            if drift_score > 0:
                # DETECTED, BUT NEVER ACTED ON BY CHANGING THE VERDICT.
                #
                # This safeguard predates the evidence-strength profile. Back
                # when the LLM itself chose the coverage label, prose that read
                # like a recommendation was good evidence the label was wrong,
                # so downgrading Covered -> Partial was reasonable.
                #
                # That reasoning is now inverted. Coverage is computed from the
                # DOCUMENT's own provisions (see evidence_strength.py), so
                # letting the phrasing of a generated paragraph override a
                # count of real binding provisions means narrative style beats
                # document evidence. It produced exactly that failure: the EU
                # AI Act's Transparency dimension — 10 binding provisions, 3
                # of them enforcement-backed — was demoted to Partial purely
                # because the synthesis paragraph contained the words "would
                # translate". Japan and India lost dimensions the same way, on
                # "needs to" and "bridge the gap", phrases that legitimately
                # describe a residual gap inside an otherwise-covered
                # dimension.
                #
                # It also leaked its own audit trail into user-facing fields
                # ("Downgraded from Covered to Partial for review..."), which
                # is internal process vocabulary no policy reader can act on.
                #
                # The drift signal is still worth keeping as a QUALITY signal:
                # it means the narrative and the verdict disagree, and the
                # narrative is the part that should be corrected. Logged for
                # telemetry, never surfaced, never verdict-changing.
                logger.warning(
                    "covered_synthesis_drift_detected",
                    dimension=dimension,
                    drift_score=drift_score,
                    drift_phrases=drift_phrases,
                    note="narrative/verdict mismatch; verdict from document evidence retained",
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
            fb_consensus, fb_differences, fb_overall = self._build_covered_synthesis_fallback(
                dimension=dimension,
                module1_chunks=retrieval.module1_chunks,
                coverage_example=coverage_example,
                operational_mechanisms=mechanisms,
            )
            was_consensus_empty = not fs_consensus
            was_differences_empty = not fs_differences
            if was_consensus_empty:
                fs_consensus = fb_consensus
            if was_differences_empty:
                fs_differences = fb_differences
            fs_overall = fb_overall
            framework_synthesis = "\n\n".join(
                p
                for p in [
                    f"Consensus: {fs_consensus}" if fs_consensus else "",
                    f"Differences: {fs_differences}" if fs_differences else "",
                    f"Overall assessment: {fs_overall}" if fs_overall else "",
                ]
                if p
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
            self._translate_chunk_ids(
                getattr(combined, "document_evidence", []) or [], label_to_id
            ),
            default_source="Uploaded Document",
            source_type="document",
        )
        fw_citations = self._verify_module_citations(
            self._translate_chunk_ids(
                getattr(combined, "framework_evidence", []) or [], label_to_id
            ),
            source_type="framework",
        )
        std_citations = self._verify_module_citations(
            self._translate_chunk_ids(
                getattr(combined, "standard_citations", []) or [], label_to_id
            ),
            source_type="framework",
        )

        # Missing / Partial findings must still carry a framework requirement
        # citation (spec), but the deterministic fallback must NEVER attach an
        # off-topic or un-sourced chunk: the fallback chunk must be
        # dimension-grounded (shared keyword check) and carry a real framework
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
            implementation_depth=depth,
            depth_reasoning=depth_reasoning,
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
        all_citations = doc_citations + fw_citations + std_citations
        evidence_list = self._build_evidence_list(all_citations, similarity_map)
        evidence_pairs = self._compute_evidence_agreement_pairs(all_citations)
        conf_score, conf_method = compute_calibrated_confidence(
            evidence_list=evidence_list,
            evidence_pairs=evidence_pairs,
            coverage_level=coverage,
            dimension=dimension,
        )
        # Risk framing from the document's own evidence, not from a restatement
        # of the coverage label. Uses the counters already computed for the
        # verdict, so it can never disagree with it.
        risk_basis = ""
        gap_consequence = ""
        try:
            risk_basis, gap_consequence = describe_risk_basis(
                coverage.value, strength_profile, determined.get("mechanisms")
            )
        except Exception as exc:
            logger.warning("risk_basis_failed", dimension=dimension, error=str(exc))
        risk, risk_reason = compute_risk(coverage, dimension, basis=risk_basis or None)

        # Persist mechanism breadth alongside the force verdict. Until now the
        # only trace of it was the sentence spliced into coverage_reasoning,
        # so nothing downstream could aggregate it — the breadth axis existed
        # in the analysis and not in the output.
        # `determined` is None when the dimension had no scored evidence at
        # all, which is exactly when there are no mechanisms to record.
        _mech = (determined or {}).get("mechanisms")
        _mech_present = dict(getattr(_mech, "present", {}) or {})
        _mech_absent = list(getattr(_mech, "absent", []) or [])

        # How much this particular cell is worth, from the same counters the
        # verdict was computed on — so the two can never disagree.
        _prof = (determined or {}).get("profile")
        _confidence_band, _confidence_reason = verdict_confidence(
            n_scored=getattr(_prof, "n_scored", 0),
            n_binding=getattr(_prof, "n_binding", 0),
            n_enforceable=getattr(_prof, "n_enforceable", 0),
            mechanisms_bound=sum(1 for t in _mech_present.values() if t >= TIER_OBLIGATORY),
        )

        gap = GovernanceGap(
            dimension=dimension,
            coverage=coverage,
            gap_found=gap_detected,
            evidence=evidence_list,
            reason_flagged=reason_flagged,
            recommendation="\n".join(recommendations) if recommendations else "",
            risk_level=risk,
            risk_reason=risk_reason,
            risk_basis=risk_basis,
            potential_consequence=gap_consequence,
            un_recommendation=recommendations[0] if recommendations else "",
            framework_synthesis=framework_synthesis,
            confidence_score=conf_score,
            confidence_method=conf_method,
            coverage_reasoning=coverage_reasoning,
            mechanisms_present=_mech_present,
            mechanisms_absent=_mech_absent,
            priority_gaps=rank_absent(dimension, _mech_absent),
            framework_corpus_size=framework_count(),
            evidence_confidence=_confidence_band,
            evidence_confidence_reason=_confidence_reason,
            mechanism_adjudication=getattr(_mech, "adjudication", "") or "",
            implementation_depth=depth,
            depth_reasoning=depth_reasoning,
            module_1=module1,
            module_2=module2,
            unverifiable_citations=_unverifiable_citations,
            fabricated_citations=_fabricated_citations,
        )

        module2_json = module2.model_dump_json()
        logger.info(
            "module_1_2_analysis_complete",
            dimension=dimension,
            coverage=coverage.value,
            implementation_depth=depth.value,
            priority=priority.value if priority else None,
            tier="best_practices" if coverage == CoverageLevel.COVERED else "recommendations",
            module2_output_chars=len(module2_json),
            num_doc_citations=len(doc_citations),
            num_fw_citations=len(fw_citations),
            num_std_citations=len(std_citations),
            num_future_strengthening_opportunities=len(future_strengthening_opportunities),
            num_international_examples=len(best_practices.international_examples)
            if best_practices
            else 0,
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
            # The prompt asks which step each passage supports, but without a
            # field to put it in the answer was dropped at parse time: every
            # one of 94 stored roadmap citations carried an empty claim, and
            # it read like the model ignoring an instruction it had in fact
            # followed. A quote nobody can tie to a step cannot be checked.
            claim: str = ""

        class IncidentSchema(BaseModel):
            incident_name: str
            source: str = ""
            # The incident's concrete facts. Without it the panel named a case
            # and then described it only in the abstract.
            what_happened: str = ""
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
            lines.append(
                f"Existing operational mechanisms in document: {'; '.join(m1.operational_mechanisms[:6])}"
            )
        if gap.implementation_depth:
            lines.append(f"Governance depth: {gap.implementation_depth.value}")
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
            must exist, and the name must be a generic description of an
            institution, never a proper name the document does not use.
          A decorated form of a body the document does name ("European AI
          Office" for "AI Office") is corrected to the document's own name.
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

            # OCR-tolerant containment, not a literal substring test. PDF
            # extraction splits words apart throughout these documents — the
            # EU AI Act yields "Off ice", "Ar ticle", "surveillance" broken
            # mid-word — so a plain `in` check fails on a body the document
            # names on nearly every page. Measured on the live EU corpus:
            # "market surveillance authorit" occurs 0 times as a literal
            # substring and 233 times once inter-character whitespace is
            # allowed. The rest of the pipeline already matches this way; this
            # gate was the last place still comparing raw strings, and it was
            # rejecting real agencies as unverifiable.
            # The corroborating "this text is about an institution" check has
            # to tolerate OCR too, or it just reintroduces the same failure a
            # layer down: the chunk naming the AI Office spells it "Off ice",
            # so a whole-word search for "office" finds nothing.
            def _in_document(candidate: str) -> bool:
                pattern = _ocr_tolerant_phrase(candidate)
                return any(
                    pattern.search(t)
                    and (_has_named_body_keyword_ocr(t) or _has_named_body_keyword_ocr(candidate))
                    for t in topical
                )

            if _in_document(name):
                return name, grounding_norm
            # The model often decorates a real body: "European AI Office" for
            # a statute that only ever says "AI Office". The shortest tail
            # that still names an institution and does appear is the
            # document's own name for it, so that is what is reported.
            words = name.split()
            for start in range(1, len(words) - 1):
                tail = " ".join(words[start:])
                if _has_keyword(tail, NAMED_BODY_KEYWORDS) and _in_document(tail):
                    return tail, "document_named"
            # document_implied: the document implies an institutional owner
            # without naming it. Only a GENERIC description of one is
            # accepted ("the national data protection authority"): it must
            # contain a named-body keyword, and nothing after its first word
            # may be capitalised or an acronym. A proper name the document
            # never uses — the stored case was "European AI Office" — is a
            # fabrication however institutional it sounds.
            generic = not any(w[:1].isupper() for w in words[1:])
            if (
                grounding_norm == "document_implied"
                and generic
                and _has_keyword(name, NAMED_BODY_KEYWORDS)
            ):
                return name, "document_implied"
            return (
                "Not specified by policy — implementation responsibility "
                "should be assigned by the adopting government.",
                "none_identified",
            )

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
        call = self._prepare_module34(dimension, gap, retrieval, country, workspace_id)
        combined = generate_with_retry(
            provider=self.provider,
            prompt=call.prompt,
            schema=self._get_module34_schema(),
            system_prompt=call.system_prompt,
            operation=f"module3_4_{dimension.lower().replace(' ', '_')}",
            debug_ctx=debug_ctx,
        )
        self._finish_module34(call, combined)

    def _prepare_module34(
        self,
        dimension: str,
        gap: GovernanceGap,
        retrieval: Module34RetrievalResult,
        country: str = "",
        workspace_id: str = "",
    ) -> _Module34Call:
        """Everything before the Module 3+4 model call: the carried-forward verdict and the prompt."""
        dimension_def = analysis_prompts.build_dimension_definition_block(dimension)
        verdict_text = self._build_dimension_verdict_text(gap)
        # Bodies the document itself names in this dimension's passages. The
        # model cannot name what it was not shown, and Module 3 sees only two
        # document chunks — see document_named_bodies. The wider scoring pool
        # is included because that is where the naming passage usually sits.
        candidate_bodies: list[str] = []
        try:
            pool: list[dict[str, Any]] = list(retrieval.document_chunks or [])
            if workspace_id and getattr(self, "retrieval_pipeline", None) is not None:
                pool += [
                    {"text": t}
                    for _cid, t in self.retrieval_pipeline._workspace_chunk_texts(workspace_id)
                ]
            candidate_bodies = document_named_bodies(pool, dimension)
        except Exception as exc:
            logger.warning("candidate_bodies_failed", dimension=dimension, error=str(exc))
        if candidate_bodies:
            logger.info(
                "candidate_bodies_offered",
                dimension=dimension,
                bodies=candidate_bodies,
            )

        sys_prompt, prompt = analysis_prompts.build_module3_4_combined_prompt(
            dimension=dimension,
            dimension_definition=dimension_def,
            dimension_verdict=verdict_text,
            module3_chunks=retrieval.module3_chunks,
            module4_chunks=retrieval.module4_chunks,
            document_chunks=retrieval.document_chunks,
            country=country,
            candidate_bodies=candidate_bodies,
        )
        return _Module34Call(
            dimension=dimension,
            gap=gap,
            retrieval=retrieval,
            workspace_id=workspace_id,
            dimension_definition=dimension_def,
            dimension_verdict=verdict_text,
            system_prompt=sys_prompt,
            prompt=prompt,
        )

    def _finish_module34(self, call: _Module34Call, combined: Any) -> None:
        """Everything after the Module 3+4 model call; sets the roadmap and cases on the gap."""
        dimension = call.dimension
        gap = call.gap
        retrieval = call.retrieval
        workspace_id = call.workspace_id

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
                phases.append(
                    Module3Phase(
                        phase=str(ph.get("phase", "") or ""),
                        timeline=str(ph.get("timeline", "") or ""),
                        objective=str(ph.get("objective", "") or ""),
                        steps=steps,
                    )
                )
            else:
                steps = [s for s in (getattr(ph, "steps", []) or []) if s][:5]
                phases.append(
                    Module3Phase(
                        phase=str(getattr(ph, "phase", "") or ""),
                        timeline=str(getattr(ph, "timeline", "") or ""),
                        objective=str(getattr(ph, "objective", "") or ""),
                        steps=steps,
                    )
                )

        raw_agency = str(getattr(combined, "responsible_agency", "") or "")
        raw_grounding = str(getattr(combined, "responsible_agency_grounding", "") or "")
        agency, grounding = self._verify_responsible_agency(
            raw_agency,
            raw_grounding,
            retrieval.document_chunks,
            dimension,
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
        # implementation depth, responsible-agency grounding, phase scope),
        # with an explicit reasoning string so the estimate is auditable.
        step_counts = [len(p.steps) for p in phases]
        timelines = estimate_phase_timelines(
            coverage=gap.coverage,
            operational_mechanisms=(gap.module_1.operational_mechanisms if gap.module_1 else []),
            depth=gap.implementation_depth,
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

        documentation = [
            d for d in (getattr(combined, "documentation_requirements", []) or []) if d
        ]
        monitoring = [m for m in (getattr(combined, "monitoring_checklist", []) or []) if m]

        # Module 3 citations — same verification path as Module 1+2, then the
        # dimension-grounding gate (same discipline as Module 4 matching): an
        # LLM citation whose chunk is NOT topically about this dimension is
        # dropped (verified-but-irrelevant is worse than honest absence) and
        # the slots are re-filled deterministically from the best
        # dimension-topical chunks in the retrieved implementation-source and
        # uploaded-document buckets.
        impl_citations_raw = self._translate_chunk_ids(
            getattr(combined, "implementation_citations", []) or [],
            label_to_id,
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
        # _chunk_matches_dimension used everywhere else). A loosely-
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
                happened = inc.get("what_happened", "") or ""
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
                happened = getattr(inc, "what_happened", "") or ""
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
            grounded_incidents.append(
                IncidentMatch(
                    incident_name=name,
                    source=src or md.get("framework", "") or "",
                    what_happened=happened,
                    dimension_relevance=rel,
                    potential_consequence=cons,
                    lessons_learned=less,
                    mitigation=mitig,
                    citation=citation,
                )
            )

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
                state.callback(dimension, gap, {**provider_info, "evaluation": evaluation_mode()})
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
                module1_regional_frameworks=resolve_regional_frameworks(country=country),
                # Dimension reserve (Module 2): dimension-tagged practical
                # tools keep a guaranteed Module 2 budget slot for their
                # dimension (same rationale as the regional reserve).
                module2_dimension_frameworks=resolve_dimension_frameworks(
                    dimension, roles=["module_2_practical"]
                ),
            )
            with state.lock:
                state.doc_chunks_per_dimension[dimension] = len(retrieval.document_chunks)
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
                self._emit_dimension(
                    state,
                    dimension,
                    gap,
                    {
                        "provider": self.provider.model_name,
                        "tier": self.provider.tier,
                        "error": "No chunks retrieved for dimension.",
                    },
                )
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
                workspace_id=workspace_id,
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
                        state.module34_call_count += 1
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

            self._emit_dimension(
                state,
                dimension,
                gap,
                {
                    "provider": self.provider.model_name,
                    "tier": self.provider.tier,
                },
            )
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
            self._emit_dimension(
                state,
                dimension,
                error_gap,
                {
                    "provider": self.provider.model_name,
                    "tier": self.provider.tier,
                    "error": str(exc),
                },
            )
            return error_gap

    @staticmethod
    def _batched_schema(item: type[BaseModel]) -> type[BaseModel]:
        class BatchedReply(BaseModel):
            dimensions: list[item]  # type: ignore[valid-type]

        return BatchedReply

    def _ask_batched(
        self,
        calls: list[Any],
        build: Callable[[list[Any], str], tuple[str, str]],
        item_schema: type[BaseModel],
        operation: str,
        country: str,
        state: _DimensionRunState,
        split_on_failure: bool = True,
        errors: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send several dimensions as one request; return each dimension's answer.

        A batch whose reply came back malformed, cut short or out of time is
        tried once more as two halves, at most two extra requests — not the
        eight a per-dimension fallback would cost. Any other failure is final
        for this run: see _split_can_help for why splitting an outage is
        worse than useless. A dimension missing from the
        reply is simply absent from the result; one lost with a failed half is
        also entered in `errors`, with the reason it failed.
        """
        if not calls:
            return {}
        start = time.time()
        try:
            system, prompt = build(calls, country)
            reply = generate_with_retry(
                provider=self.provider,
                prompt=prompt,
                schema=self._batched_schema(item_schema),
                system_prompt=system,
                operation=operation,
                debug_ctx={"num_chunks": len(calls)},
                max_output_tokens=BATCH_MAX_OUTPUT_TOKENS,
            )
            answers = list(getattr(reply, "dimensions", None) or [])
        except Exception as exc:
            with state.lock:
                state.total_llm_latency += time.time() - start
            logger.warning(
                "batched_call_failed",
                operation=operation,
                dimensions=[c.dimension for c in calls],
                error=str(exc)[:300],
            )
            if len(calls) == 1 or not split_on_failure or not _split_can_help(exc):
                raise
            half = len(calls) // 2
            out: dict[str, Any] = {}
            for part in (calls[:half], calls[half:]):
                try:
                    out.update(
                        self._ask_batched(
                            part, build, item_schema, f"{operation}_part", country, state, False
                        )
                    )
                except Exception as part_exc:
                    if errors is not None:
                        errors.update({c.dimension: str(part_exc) for c in part})
            return out
        with state.lock:
            state.llm_call_count += 1
            state.total_llm_latency += time.time() - start

        def norm(name: Any) -> str:
            return " ".join(str(name or "").split()).lower()

        by_name = {norm(getattr(a, "dimension", "")): a for a in answers}
        matched: dict[str, Any] = {}
        for i, call in enumerate(calls):
            answer = by_name.get(norm(call.dimension))
            # The model is told to echo each section's name exactly; if it
            # abbreviated one, a reply of the right length in the right order
            # still identifies it by position.
            if answer is None and len(answers) == len(calls):
                candidate = answers[i]
                if norm(getattr(candidate, "dimension", "")) not in {
                    norm(c.dimension) for c in calls
                }:
                    answer = candidate
            if answer is not None:
                matched[call.dimension] = answer
        return matched

    def _ask_each(
        self,
        calls: list[_DimensionCall],
        num_frameworks: int,
        state: _DimensionRunState,
        errors: dict[str, str],
    ) -> dict[str, Any]:
        """Module 1+2 as one request per dimension, run concurrently.

        Each dimension is sent the exact prompt the per-dimension path sends and
        gets a reply of its own. A failure is entered in `errors` and costs only
        that dimension — unless the provider refused it (503, 504, quota): then
        the dimensions not yet sent are failed with the same reason instead of
        spending three attempts each on a model that is turning work away. On
        27 Sep one outage cost 25 requests this way before the change. A re-run
        picks up only what failed.
        """
        refused: list[str] = []
        refused_lock = threading.Lock()

        def ask(call: _DimensionCall) -> tuple[str, Any, str]:
            if refused:
                return call.dimension, None, refused[0]
            start = time.time()
            try:
                answer = generate_with_retry(
                    provider=self.provider,
                    prompt=call.prompt,
                    schema=self._get_combined_module_schema(),
                    system_prompt=call.system_prompt,
                    operation=f"module1_2_{call.dimension.lower().replace(' ', '_')}",
                    debug_ctx={
                        "num_chunks": call.retrieval.total_chunks,
                        "num_frameworks": num_frameworks,
                    },
                )
            except Exception as exc:
                logger.warning(
                    "dimension_evaluation_failed", dimension=call.dimension, error=str(exc)[:300]
                )
                if not _reply_was_malformed(exc):
                    with refused_lock:
                        refused.append(str(exc))
                return call.dimension, None, str(exc)
            finally:
                with state.lock:
                    state.total_llm_latency += time.time() - start
            with state.lock:
                state.llm_call_count += 1
            return call.dimension, answer, ""

        answers: dict[str, Any] = {}
        if not calls:
            return answers
        with ThreadPoolExecutor(
            max_workers=max(1, min(ANALYSIS_MAX_CONCURRENCY, len(calls)))
        ) as pool:
            for dimension, answer, error in pool.map(ask, calls):
                if answer is None:
                    errors[dimension] = error
                else:
                    answers[dimension] = answer
        return answers

    def _analyze_pending_batched(
        self,
        pending: list[str],
        workspace_id: str,
        num_frameworks: int,
        country: str | None,
        state: _DimensionRunState,
    ) -> dict[str, GovernanceGap]:
        """Every pending dimension, with the Module 3+4 requests shared.

        The per-dimension work before and after each request is unchanged —
        routing, retrieval, the precomputed verdict, and every line of the
        answer handling are the same methods the per-dimension path calls. Only
        the transport differs: the Module 3+4 answers for the gapped dimensions
        arrive in one reply, and with BATCH_EVALUATION so do the Module 1+2
        answers; otherwise each dimension's evaluation is its own request.
        """
        country = country or ""
        results: dict[str, GovernanceGap] = {}
        calls: list[_DimensionCall] = []
        for dimension in pending:
            try:
                routed_frameworks = resolve_frameworks(dimension, country=country)
                retrieval = self.retrieval_pipeline.retrieve_module_chunks(
                    dimension=dimension,
                    workspace_id=workspace_id,
                    module1_frameworks=routed_frameworks,
                    module1_regional_frameworks=resolve_regional_frameworks(country=country),
                    module2_dimension_frameworks=resolve_dimension_frameworks(
                        dimension, roles=["module_2_practical"]
                    ),
                )
                with state.lock:
                    state.doc_chunks_per_dimension[dimension] = len(retrieval.document_chunks)
                    state.all_retrieved.extend(retrieval.all_chunks_labeled())
                if retrieval.total_chunks == 0:
                    results[dimension] = self._build_insufficient_gap(dimension)
                    continue
                calls.append(
                    self._prepare_dimension_combined(dimension, retrieval, country, workspace_id)
                )
            except Exception as exc:
                logger.error("dimension_analysis_failed", dimension=dimension, error=str(exc))
                results[dimension] = self._build_error_gap(dimension, str(exc))

        part_errors: dict[str, str] = {}
        batch_error = "The analysis reply did not include this dimension."
        if not BATCH_EVALUATION:
            answers = self._ask_each(calls, num_frameworks, state, part_errors)
        else:
            try:
                answers = self._ask_batched(
                    calls,
                    analysis_prompts.build_module1_2_batched_prompt,
                    self._get_combined_module_schema(),
                    "module1_2_batch",
                    country,
                    state,
                    errors=part_errors,
                )
            except Exception as exc:
                answers = {}
                batch_error = str(exc)
        for call in calls:
            answer = answers.get(call.dimension)
            if answer is None:
                results[call.dimension] = self._build_error_gap(
                    call.dimension, part_errors.get(call.dimension, batch_error)
                )
                continue
            try:
                results[call.dimension] = self._finish_dimension_combined(call, answer)
            except Exception as exc:
                logger.error("dimension_analysis_failed", dimension=call.dimension, error=str(exc))
                results[call.dimension] = self._build_error_gap(call.dimension, str(exc))

        # Module 3+4 for the gapped dimensions, in one request. A failure here
        # leaves the verdicts standing and the roadmap absent, as it always did.
        m34_calls: list[_Module34Call] = []
        for dimension in pending:
            gap = results.get(dimension)
            if gap is None or gap.analysis_error:
                continue
            if gap.coverage not in (CoverageLevel.PARTIAL, CoverageLevel.MISSING):
                continue
            try:
                m34_retrieval = self.retrieval_pipeline.retrieve_module34_chunks(
                    dimension=dimension,
                    workspace_id=workspace_id,
                    module3_dimension_frameworks=resolve_dimension_frameworks(
                        dimension, roles=["module_3_implementation"]
                    ),
                )
                m34_calls.append(
                    self._prepare_module34(dimension, gap, m34_retrieval, country, workspace_id)
                )
            except Exception as exc:
                logger.warning("module_3_4_analysis_failed", dimension=dimension, error=str(exc))
        if m34_calls:
            calls_before = state.llm_call_count
            try:
                m34_answers = self._ask_batched(
                    m34_calls,
                    analysis_prompts.build_module3_4_batched_prompt,
                    self._get_module34_schema(),
                    "module3_4_batch",
                    country,
                    state,
                )
            except Exception as exc:
                logger.warning("module_3_4_analysis_failed", error=str(exc))
                m34_answers = {}
            with state.lock:
                state.module34_call_count += state.llm_call_count - calls_before
            for call in m34_calls:
                answer = m34_answers.get(call.dimension)
                if answer is None:
                    logger.warning("module_3_4_analysis_failed", dimension=call.dimension)
                    continue
                try:
                    self._finish_module34(call, answer)
                except Exception as exc:
                    logger.warning(
                        "module_3_4_analysis_failed", dimension=call.dimension, error=str(exc)
                    )

        for dimension in pending:
            gap = results[dimension]
            info = {"provider": self.provider.model_name, "tier": self.provider.tier}
            if gap.analysis_error:
                info["error"] = gap.analysis_error
            self._emit_dimension(state, dimension, gap, info)
        return results

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
        # worker pool (ANALYSIS_MAX_CONCURRENCY; the free-tier setup runs 3), paced
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
            self._prepare_workspace(workspace_id, country or "")
            max_workers = max(1, ANALYSIS_MAX_CONCURRENCY)
            if BATCH_LLM_CALLS:
                dimension_results.update(
                    self._analyze_pending_batched(
                        pending, workspace_id, num_frameworks, country, state
                    )
                )
            elif max_workers > 1 and len(pending) > 1:
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {
                        pool.submit(
                            self._analyze_one_dimension,
                            d,
                            workspace_id,
                            num_frameworks,
                            country,
                            state,
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
                        d,
                        workspace_id,
                        num_frameworks,
                        country,
                        state,
                    )

        complete_results = [dimension_results[d] for d in GOVERNANCE_DIMENSIONS]
        all_retrieved = state.all_retrieved
        doc_chunks_per_dimension = state.doc_chunks_per_dimension
        llm_call_count = state.llm_call_count + getattr(self, "_adjudication_calls", 0)
        total_llm_latency = state.total_llm_latency

        for g in complete_results:
            if g.coverage == CoverageLevel.INSUFFICIENT_EVIDENCE:
                continue
            risk, reason = compute_risk(
                coverage=g.coverage,
                dimension=g.dimension,
                other_gaps=complete_results,
                # Re-apply the evidence-derived basis. Without this the
                # cross-dimension pass overwrites it with the generic sentence,
                # which is what shipped: every stored gap carried
                # "Core/Supporting dimension X is partially addressed".
                basis=g.risk_basis or None,
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
            entry = tier_stats.setdefault(
                tier, {"count": 0, "module2_chars": 0, "module2_avg_chars": 0.0}
            )
            entry["count"] += 1
            if g.module_2 is not None:
                entry["module2_chars"] += len(g.module_2.model_dump_json())
        for entry in tier_stats.values():
            entry["module2_avg_chars"] = (
                round(entry["module2_chars"] / entry["count"], 1) if entry["count"] else 0.0
            )
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
                gap = next(
                    (g for g in complete_results if g.dimension == violation.dimension), None
                )
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
            module34_calls=state.module34_call_count,
            adjudication_calls=getattr(self, "_adjudication_calls", 0),
            consistency_passed=consistency_report.passed,
            consistency_score=consistency_report.score,
            decision_analytics=decision_analytics,
        )

        log_run_summary()

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
            # The provider's own error stays in analysis_error for whoever
            # debugs the run. A policy reader gets the fact and the remedy —
            # "All Gemini API keys exhausted for 'module1_2_...'" is neither.
            reason_flagged="This dimension could not be assessed on this run.",
            recommendation="Re-run the analysis to assess this dimension.",
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
            1
            for g in gaps
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
            parts.append(
                f"{len(errored)} dimension(s) could not be assessed on this run "
                f"({', '.join(g.dimension for g in errored)})."
            )
        if insufficient > 0:
            parts.append(f"{insufficient} dimensions had insufficient evidence.")
        if dimensions_missing:
            parts.append(f"Missing: {', '.join(dimensions_missing)}.")
        if dimensions_partial:
            parts.append(f"Partial: {', '.join(dimensions_partial)}.")

        return " ".join(parts)
