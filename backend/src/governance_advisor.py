"""AI Rapporteur — intelligent intent classification and response generation.

Architecture:
  - IntentClassifier: Determines user intent from message + session context
  - ResponseGenerator: Generates structured responses per intent
  - SessionContext: Tracks active dimension, history, and conversation state
  - PluginRegistry: Extensible handler for future capabilities (comparisons,
    benchmarks, compliance reports, etc.) — new plugins register without
    modifying classification logic.
"""

from __future__ import annotations

import re
import time
import structlog
from enum import Enum
from typing import Any, Callable
from abc import ABC, abstractmethod

from src.analysis_prompts import DIMENSION_DEFINITIONS
from src.deterministic import LEVEL_LABELS
from src.gap_analyzer import GOVERNANCE_DIMENSIONS

logger = structlog.get_logger()

# ── Intents ──────────────────────────────────────────────────────────────

class Intent(str, Enum):
    CONCEPT_EXPLANATION = "concept_explanation"
    ANALYSIS_EXPLANATION = "analysis_explanation"
    RECOMMENDATION_EXPLANATION = "recommendation_explanation"
    EDUCATIONAL = "educational"
    GENERAL = "general"
    GREETING = "greeting"
    UNKNOWN = "unknown"


# ── Governance Knowledge Base ────────────────────────────────────────────

# Imported from src.gap_analyzer: GOVERNANCE_DIMENSIONS

DIMENSION_ALIASES: dict[str, list[str]] = {
    "Transparency": ["transparency", "explainability", "explainable", "openness", "disclosure", "audit", "reporting"],
    "Accountability": ["accountability", "responsible", "liability", "oversight", "redress", "grievance", "responsibility"],
    "Privacy": ["privacy", "data protection", "personal data", "consent", "anonymization", "confidentiality"],
    "Safety": ["safety", "robustness", "reliability", "security", "fail.?safe", "incident", "risk assessment"],
    "Human Autonomy": ["autonomy", "human control", "human.?in.?the.?loop", "human oversight", "opt.?out", "self.?determination"],
    "Inclusivity": ["inclusivity", "inclusion", "accessibility", "equity", "participation", "digital divide", "multi.?stakeholder"],
    "Fairness": ["fairness", "bias", "discrimination", "non.?discrimination", "equality", "equitable"],
    "Environmental Sustainability": ["environmental", "sustainability", "sustainable", "energy", "carbon", "ecological", "climate"],
}


# ── Session Context ──────────────────────────────────────────────────────

class SessionContext:
    """Tracks active conversation state — which dimension, what was discussed,
    and the last few messages for follow-up resolution."""

    def __init__(self) -> None:
        self.active_dimension: str | None = None
        self.active_topic: str | None = None
        self.history: list[dict[str, str]] = []
        self.last_intent: Intent = Intent.UNKNOWN
        self.finding_context: dict[str, Any] | None = None

    def update(
        self,
        message: str,
        reply: str,
        intent: Intent,
        dimension: str | None = None,
    ) -> None:
        if dimension:
            self.active_dimension = dimension
        self.last_intent = intent
        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": reply})
        # Keep last 6 messages (3 turns)
        if len(self.history) > 6:
            self.history = self.history[-6:]

    def set_finding_context(self, ctx: dict[str, Any] | None) -> None:
        self.finding_context = ctx
        if ctx and ctx.get("dimension"):
            self.active_dimension = ctx["dimension"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_dimension": self.active_dimension,
            "active_topic": self.active_topic,
            "last_intent": self.last_intent.value if self.last_intent else None,
            "has_finding_context": self.finding_context is not None,
        }


# ── Intent Classifier ────────────────────────────────────────────────────

# Patterns for detecting governance dimensions in text
_DIMENSION_PATTERN = re.compile(
    r"(transparency|accountability|privacy|safety|human autonomy|"
    r"inclusivity|fairness|environmental sustainability|"
    r"explainability|bias|discrimination|data protection|"
    r"human.?in.?the.?loop|algorithmic|governance|maturity)",
    re.IGNORECASE,
)

_CONCEPT_PATTERNS = re.compile(
    r"^(what\s+is|what's|what does|explain|define|describe|"
    r"what (do|does) you mean by|tell me about|what are|what's the)",
    re.IGNORECASE,
)

_ANALYSIS_PATTERNS = re.compile(
    r"(why\s+is|why\s+was|why\s+did|how\s+is|how\s+was|"
    r"what does.*mean|what (is|was) the (reason|rationale|evidence)|"
    r"explain the (coverage|risk|maturity|finding|result)|"
    r"why (is|was) it (covered|partial|missing|high|medium|low))",
    re.IGNORECASE,
)

_RECOMMENDATION_PATTERNS = re.compile(
    r"(how\s+(to|can|should|would|do|does)|"
    r"what (would|should|steps|actions|measures|practices)|"
    r"implement|implementation|recommend|improve|strengthen|"
    r"best practice|timeline|challenge)",
    re.IGNORECASE,
)

_EDUCATIONAL_PATTERNS = re.compile(
    r"(difference\s+between|compare|versus|vs\.?|"
    r"how does|what is the (relationship|link|connection)|"
    r"explain the (difference|relationship|concept))",
    re.IGNORECASE,
)

_GREETING_PATTERNS = re.compile(
    r"^(hello|hi|hey|good morning|good afternoon|good evening|"
    r"thanks|thank you|how are you|what'?s up)",
    re.IGNORECASE,
)

_FOLLOW_UP_PATTERNS = re.compile(
    r"^(why\s+is\s+this|how\s+(can|does)|explain\s+(this|that|it)|"
    r"show\s+(me|the)|give\s+(an|me)|what\s+about|and\s+)",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return text.strip().lower()


def _extract_dimension(text: str) -> str | None:
    """Extract a governance dimension from text, handling aliases."""
    normalized = _normalize(text)
    for dim, aliases in DIMENSION_ALIASES.items():
        for alias in aliases:
            if re.search(alias, normalized):
                return dim
    match = _DIMENSION_PATTERN.search(normalized)
    if match:
        matched = match.group(1).lower()
        for dim, aliases in DIMENSION_ALIASES.items():
            if matched in [a.lower() for a in aliases] or matched == dim.lower():
                return dim
        # direct match
        for dim in GOVERNANCE_DIMENSIONS:
            if dim.lower() == matched:
                return dim
    return None


def classify_intent(
    message: str,
    context: SessionContext | None = None,
) -> tuple[Intent, str | None]:
    """Classify the user message into an intent and optional dimension."""
    normalized = _normalize(message)

    # Greeting check
    if _GREETING_PATTERNS.match(normalized):
        return Intent.GREETING, None

    # Follow-up check — resolve to active dimension from context
    is_follow_up = bool(_FOLLOW_UP_PATTERNS.match(normalized))
    dimension = _extract_dimension(message)

    # If it's a follow-up and no dimension found, use the active one
    if is_follow_up and not dimension and context and context.active_dimension:
        dimension = context.active_dimension

    # If no dimension from text, check context
    if not dimension and context and context.active_dimension:
        # Check if the message might relate to the active topic
        if is_follow_up or len(message.split()) < 5:
            dimension = context.active_dimension

    # Intent classification
    if _CONCEPT_PATTERNS.match(normalized):
        return Intent.CONCEPT_EXPLANATION, dimension

    if _EDUCATIONAL_PATTERNS.search(normalized):
        return Intent.EDUCATIONAL, dimension

    if _ANALYSIS_PATTERNS.search(normalized):
        return Intent.ANALYSIS_EXPLANATION, dimension

    if _RECOMMENDATION_PATTERNS.search(normalized):
        return Intent.RECOMMENDATION_EXPLANATION, dimension

    # If dimension mentioned but no specific pattern, it's a concept question
    if dimension:
        return Intent.CONCEPT_EXPLANATION, dimension

    return Intent.GENERAL, None


# ── Response Generators ──────────────────────────────────────────────────

def _get_dimension_definition(dimension: str) -> str:
    """Get a human-readable definition for a governance dimension."""
    items = DIMENSION_DEFINITIONS.get(dimension, [])
    if items:
        return items[0] if items else ""
    return ""


def _get_dimension_aspects(dimension: str) -> list[str]:
    """Get the key aspects of a governance dimension."""
    return DIMENSION_DEFINITIONS.get(dimension, [])


def _get_maturity_level_description(level: int) -> str:
    """Get a description of a maturity level."""
    return LEVEL_LABELS.get(level, f"Level {level}")


def _build_concept_response(
    dimension: str,
    definition: str,
    aspects: list[str],
) -> str:
    """Build a structured concept explanation response."""
    lines: list[str] = []
    lines.append(f"## {dimension}")
    lines.append("")
    lines.append(definition)
    lines.append("")
    lines.append("### Why It Matters")
    lines.append("")
    lines.append(
        f"{dimension} is a core principle in AI governance. It ensures that "
        f"AI systems are developed and deployed in ways that respect human rights, "
        f"build trust, and promote accountability. International frameworks like "
        f"the UNESCO Recommendation on the Ethics of AI and the OECD AI Principles "
        f"identify {dimension.lower()} as a foundational requirement for trustworthy AI."
    )
    lines.append("")
    lines.append("### Key Aspects")
    lines.append("")
    for aspect in aspects:
        lines.append(f"• {aspect}")
    lines.append("")
    lines.append("### Relevant Governance Frameworks")
    lines.append("")
    lines.append(
        "• **UNESCO Recommendation on the Ethics of AI** — Provides value-based "
        "principles for ethical AI governance.\n"
        "• **OECD AI Principles** — Sets international standards for responsible "
        "AI stewardship.\n"
        "• **UN Global Digital Compact** — Establishes commitments for inclusive "
        "digital governance.\n"
        "• **UNDP Digital Strategy** — Guides AI for sustainable development."
    )
    return "\n".join(lines)


def _gap_to_finding_context(gap: dict[str, Any]) -> dict[str, Any]:
    """Map a saved governance-gap dict (including Module 1-4 fields) to the flat
    context shape the response generators read."""
    m1 = gap.get("module_1") or {}
    m2 = gap.get("module_2") or {}
    m3 = gap.get("module_3") or {}
    m4 = gap.get("module_4") or {}
    m1 = m1 if isinstance(m1, dict) else {}
    m2 = m2 if isinstance(m2, dict) else {}
    m3 = m3 if isinstance(m3, dict) else {}
    m4 = m4 if isinstance(m4, dict) else {}
    return {
        "dimension": gap.get("dimension"),
        "coverage": gap.get("coverage"),
        "coverage_reasoning": m1.get("coverage_reasoning") or gap.get("coverage_reasoning"),
        "coverage_example": m1.get("coverage_example"),
        "governance_maturity": m1.get("governance_maturity") or gap.get("governance_maturity"),
        "maturity_reasoning": m1.get("maturity_reasoning") or gap.get("maturity_reasoning"),
        "gap_found": m1.get("gap_detected", gap.get("gap_found")),
        "reason_flagged": m1.get("reason_flagged") or gap.get("reason_flagged"),
        "risk_level": gap.get("risk_level"),
        "risk_reason": gap.get("risk_reason"),
        "recommendation": gap.get("recommendation"),
        "recommendations": m2.get("recommendations") or [],
        "priority": m2.get("priority"),
        "framework_synthesis": m2.get("framework_synthesis") or gap.get("framework_synthesis"),
        "un_recommendation": gap.get("un_recommendation"),
        "best_practices": m2.get("best_practices"),
        "roadmap": m3,
        "case_intelligence": m4,
        "evidence": gap.get("evidence", []),
    }


def _build_analysis_explanation(
    dimension: str,
    finding_context: dict[str, Any] | None,
    analysis_results: dict[str, Any] | None = None,
) -> str:
    """Build a structured analysis explanation response.

    Uses the passed finding_context (from the "Ask about this finding" button)
    when present; otherwise resolves the dimension against the saved analysis
    results so a plain question like "Why is Fairness Partial?" gets the real
    gap record — not a generic non-answer.
    """
    ctx = finding_context or {}
    if not ctx and analysis_results:
        gap = analysis_results.get("gaps", {}).get(dimension)
        if gap:
            ctx = _gap_to_finding_context(gap)
    if not ctx:
        return (
            f"I don't have the analysis results for {dimension} available "
            f"right now. The analysis may still be processing, or there may "
            f"not be a completed analysis for the current workspace."
        )

    coverage = ctx.get("coverage", "N/A")
    risk = ctx.get("risk_level", "N/A")
    risk_reason = ctx.get("risk_reason", "")
    recommendation = ctx.get("recommendation", "")
    recommendations = ctx.get("recommendations") or []
    evidence = ctx.get("evidence", [])

    lines: list[str] = []
    lines.append(f"## Why {dimension} is {coverage}")
    lines.append("")

    # Coverage explanation
    coverage_explanations = {
        "Covered": (
            f"The analysis found that the uploaded policy document **substantively addresses** "
            f"{dimension.lower()}. This means the document discusses relevant principles, "
            f"establishes mechanisms, or commits to actions that align with international "
            f"governance expectations."
        ),
        "Partial": (
            f"The analysis found that the uploaded policy document **partially addresses** "
            f"{dimension.lower()}. The document may touch on relevant concepts but does "
            f"not provide comprehensive treatment or establish concrete mechanisms."
        ),
        "Missing": (
            f"The analysis found that the uploaded policy document **does not substantively "
            f"address** {dimension.lower()}. No evidence was found of relevant principles, "
            f"mechanisms, or commitments."
        ),
    }

    explanation = coverage_explanations.get(
        coverage,
        "The analysis could not determine a definitive coverage level for this dimension."
    )
    lines.append(explanation)
    lines.append("")

    # Deterministic reasoning behind the assigned level (Module 1)
    coverage_reasoning = ctx.get("coverage_reasoning") or ctx.get("reason_flagged")
    if coverage_reasoning:
        lines.append("### Why this level was assigned")
        lines.append("")
        lines.append(coverage_reasoning)
        lines.append("")

    # Fully Covered tier: document-grounded examples leading to the verdict
    coverage_example = ctx.get("coverage_example")
    if coverage == "Covered" and coverage_example:
        lines.append("### What the document does (coverage examples)")
        lines.append("")
        lines.append(coverage_example)
        lines.append("")

    # Governance maturity (Module 1)
    maturity = ctx.get("governance_maturity")
    if maturity:
        lines.append(f"### Governance Maturity: {maturity}")
        maturity_reasoning = ctx.get("maturity_reasoning")
        if maturity_reasoning:
            lines.append("")
            lines.append(maturity_reasoning)
        lines.append("")

    # Risk explanation
    if risk and risk != "Insufficient Evidence":
        lines.append(f"### Risk Assessment: {risk}")
        lines.append("")
        if risk_reason:
            lines.append(risk_reason)
            lines.append("")

    # Evidence summary
    if evidence:
        lines.append("### Key Evidence Found")
        lines.append("")
        for i, ev in enumerate(evidence[:5], 1):
            source = ev.get("source_framework", "Uploaded Document")
            page = f" (p. {ev.get('page_number')})" if ev.get("page_number") else ""
            text = ev.get("text", "")[:200]
            lines.append(f"**{i}.** [{source}{page}] {text}...")
        lines.append("")
        if len(evidence) > 5:
            lines.append(f"*({len(evidence) - 5} more evidence items available)*")
            lines.append("")

    # Recommendation (Module 2)
    if recommendation or recommendations:
        lines.append("### Recommendation")
        lines.append("")
        if recommendations:
            for r in recommendations:
                lines.append(f"• {r}")
        else:
            lines.append(recommendation)
        lines.append("")

    # Implementation roadmap highlights (Module 3)
    roadmap = ctx.get("roadmap") or {}
    phases = roadmap.get("phases") or []
    if phases:
        lines.append("### Implementation Roadmap (highlights)")
        lines.append("")
        for ph in phases[:3]:
            phase = ph.get("phase") or "Phase"
            timeline = ph.get("timeline") or ""
            objective = ph.get("objective") or ""
            lines.append(
                f"• **{phase}**{f' ({timeline})' if timeline else ''}: {objective}"
            )
        agency = roadmap.get("responsible_agency")
        if agency:
            lines.append("")
            lines.append(f"Responsible agency: {agency}")
        lines.append("")

    # Case intelligence (Module 4)
    case_info = ctx.get("case_intelligence") or {}
    if case_info.get("matched") and case_info.get("incident_matches"):
        lines.append("### Relevant Incident (Case Intelligence)")
        lines.append("")
        for inc in case_info["incident_matches"][:2]:
            name = inc.get("incident_name", "Incident")
            lines.append(f"• **{name}**")
            if inc.get("potential_consequence"):
                lines.append(
                    f"  Potential consequence: {str(inc['potential_consequence'])[:220]}"
                )
        lines.append("")

    return "\n".join(lines)


def _build_recommendation_response(
    dimension: str,
    finding_context: dict[str, Any] | None,
    analysis_results: dict[str, Any] | None = None,
) -> str:
    """Build a structured recommendation explanation."""
    ctx = finding_context or {}
    if not ctx and analysis_results:
        gap = analysis_results.get("gaps", {}).get(dimension)
        if gap:
            ctx = _gap_to_finding_context(gap)

    recommendation = ctx.get("recommendation", "")
    recommendations = ctx.get("recommendations") or []
    priority = ctx.get("priority")
    un_rec = ctx.get("un_recommendation", "")
    framework_synthesis = ctx.get("framework_synthesis", "")
    best = ctx.get("best_practices") or {}
    roadmap = ctx.get("roadmap") or {}
    evidence = ctx.get("evidence", [])

    lines: list[str] = []
    lines.append(f"## Implementing Recommendations for {dimension}")
    lines.append("")

    if priority:
        lines.append(f"**Priority: {priority}**")
        lines.append("")

    recs = recommendations if recommendations else ([recommendation] if recommendation else [])
    if recs:
        lines.append("### Recommended Actions")
        lines.append("")
        for r in recs:
            lines.append(f"• {r}")
        lines.append("")

    # Fully Covered tier: best-practices framing instead of gap-filling language
    opening = best.get("opening")
    if opening:
        lines.append("### Best Practices (alignment already strong)")
        lines.append("")
        lines.append(opening)
        opportunities = best.get("future_strengthening_opportunities") or []
        if opportunities:
            lines.append("")
            lines.append("Future strengthening opportunities:")
            for opp in opportunities:
                lines.append(f"• {opp}")
        intl = best.get("international_examples") or []
        if intl:
            lines.append("")
            lines.append("International examples:")
            for ex in intl[:3]:
                practice = ex.get("practice", "")
                src = ex.get("country_or_source") or ex.get("reference") or ""
                lines.append(f"• {practice}" + (f" ({src})" if src else ""))
        lines.append("")

    if un_rec:
        lines.append("### Smallest Effective Improvement")
        lines.append("")
        lines.append(un_rec)
        lines.append("")

    lines.append("### Implementation Steps")
    lines.append("")
    lines.append(
        "1. **Assess Current State** — Review existing policies, mechanisms, "
        "and institutional arrangements related to this dimension.\n"
        "2. **Identify Gaps** — Compare current state against international "
        "framework requirements (UNESCO, OECD, UN).\n"
        "3. **Develop Action Plan** — Create a phased implementation roadmap "
        "with clear milestones and responsible entities.\n"
        "4. **Build Capacity** — Invest in training, tools, and institutional "
        "capabilities needed for implementation.\n"
        "5. **Monitor and Review** — Establish metrics and periodic review "
        "mechanisms to track progress."
    )
    lines.append("")

    # Module 3 roadmap phases + responsible agency
    phases = roadmap.get("phases") or []
    if phases:
        lines.append("### Phased Roadmap (Module 3)")
        lines.append("")
        for ph in phases:
            name = ph.get("phase") or "Phase"
            timeline = ph.get("timeline") or ""
            objective = ph.get("objective") or ""
            header = f"**{name}**" + (f" ({timeline})" if timeline else "")
            lines.append(f"• {header}: {objective}")
        agency = roadmap.get("responsible_agency")
        if agency:
            lines.append("")
            lines.append(f"**Responsible agency:** {agency}")
        lines.append("")

    if framework_synthesis:
        lines.append("### Framework Alignment")
        lines.append("")
        lines.append(framework_synthesis)
        lines.append("")

    lines.append("### Expected Benefits")
    lines.append("")
    lines.append(
        "• Stronger alignment with international governance standards\n"
        "• Enhanced trust among citizens and international partners\n"
        "• Reduced risk of AI-related harms\n"
        "• Improved accountability and oversight\n"
        "• Better preparedness for emerging regulatory requirements"
    )
    lines.append("")

    if evidence:
        lines.append("### Supporting Evidence")
        lines.append("")
        for ev in evidence[:3]:
            lines.append(f"• {ev.get('text', '')[:150]}...")

    return "\n".join(lines)


def _build_educational_response(
    message: str,
    dimension: str | None,
) -> str:
    """Build a structured educational response for comparative questions."""
    # Extract comparison terms
    normalized = _normalize(message)
    
    # Check for common comparison patterns
    comparisons: dict[str, tuple[str, str]] = {}
    
    if "responsible" in normalized and "ethical" in normalized:
        comparisons["Responsible AI vs Ethical AI"] = (
            "**Responsible AI** refers to the practice of designing, developing, "
            "and deploying AI systems with good intention, considering the broader "
            "societal impacts. It encompasses governance structures, accountability "
            "mechanisms, and organizational practices.\n\n"
            "**Ethical AI** focuses on the moral principles that guide AI development — "
            "fairness, transparency, privacy, and human rights. It's more concerned "
            "with the *what* (what principles should guide AI) while Responsible AI "
            "is more concerned with the *how* (how to operationalize those principles).\n\n"
            "Both concepts are complementary. Ethical AI sets the normative framework; "
            "Responsible AI provides the operational approach to implement it."
        )
    
    if "governance" in normalized and "regulation" in normalized:
        comparisons["Governance vs Regulation"] = (
            "**AI Governance** is the broader system of rules, practices, "
            "processes, and institutions that guide the development and use of AI. "
            "It includes both formal and informal mechanisms — laws, policies, "
            "ethical codes, technical standards, and multi-stakeholder bodies.\n\n"
            "**AI Regulation** is a subset of governance — the binding legal rules "
            "enforced by authorities. Regulation provides enforceable obligations "
            "(e.g., the EU AI Act), while governance encompasses the wider ecosystem "
            "of norms, principles, and voluntary standards.\n\n"
            "Think of governance as the entire playing field, and regulation as "
            "the specific rules of the game with enforcement mechanisms."
        )

    if comparisons:
        lines: list[str] = []
        for title, content in comparisons.items():
            lines.append(f"## {title}")
            lines.append("")
            lines.append(content)
        return "\n".join(lines)

    # Generic educational response
    if dimension:
        return _build_concept_response(
            dimension,
            _get_dimension_definition(dimension),
            _get_dimension_aspects(dimension),
        )
    
    return (
        "I'd be happy to explain AI governance concepts. You can ask about:\n\n"
        "• **Specific dimensions**: What is transparency? Explain accountability.\n"
        "• **Comparisons**: Difference between Responsible AI and Ethical AI?\n"
        "• **Concepts**: What is an Algorithmic Impact Assessment?\n\n"
        "Which topic interests you?"
    )


def _build_greeting_response() -> str:
    return (
        "Hello! I'm the AI Rapporteur. I can help you understand:\n\n"
        "• **Analysis Results** — Why a dimension received a particular coverage "
        "or risk level in your policy analysis\n"
        "• **Governance Concepts** — What AI governance principles like "
        "transparency, fairness, or accountability mean\n"
        "• **Recommendations** — How to implement governance improvements "
        "based on international best practices\n"
        "• **Educational Topics** — Differences between governance concepts, "
        "framework comparisons, and more\n\n"
        "What would you like to explore?"
    )


def _build_unknown_response() -> str:
    return (
        "I'm not sure I understand your question. I specialize in AI governance "
        "and policy analysis. Here are some things you can ask me:\n\n"
        "• **About your analysis**: \"Why is Fairness Partial?\" or "
        "\"Explain the Transparency finding\"\n"
        "• **About concepts**: \"What is AI accountability?\" or "
        "\"Define algorithmic fairness\"\n"
        "• **About recommendations**: \"How can Privacy be improved?\" or "
        "\"What would bias auditing look like?\"\n"
        "• **Educational**: \"Difference between governance and regulation?\"\n\n"
        "Can you rephrase your question?"
    )


def build_concept_response(dimension: str) -> str:
    """Public wrapper — structured concept explanation for a dimension."""
    return _build_concept_response(
        dimension,
        _get_dimension_definition(dimension),
        _get_dimension_aspects(dimension),
    )


def build_educational_response(message: str, dimension: str | None) -> str:
    """Public wrapper — structured educational response."""
    return _build_educational_response(message, dimension)


# ── Plugin Interface ─────────────────────────────────────────────────────

class AdvisorPlugin(ABC):
    """Base class for future capabilities that plug into the advisor without
    modifying the intent classification logic."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def can_handle(self, intent: Intent, dimension: str | None, message: str) -> bool:
        """Return True if this plugin should handle the request."""
        ...

    @abstractmethod
    def handle(
        self,
        message: str,
        intent: Intent,
        dimension: str | None,
        session: SessionContext,
        retrieval_context: str | None = None,
    ) -> str | None:
        """Handle the request and return a response, or None to fall through."""
        ...


class PluginRegistry:
    """Maintains a list of plugins and dispatches requests to matching ones."""

    def __init__(self) -> None:
        self._plugins: list[AdvisorPlugin] = []

    def register(self, plugin: AdvisorPlugin) -> None:
        self._plugins.append(plugin)
        logger.info("advisor_plugin_registered", plugin=plugin.name)

    def get_handler(
        self,
        intent: Intent,
        dimension: str | None,
        message: str,
    ) -> AdvisorPlugin | None:
        for plugin in self._plugins:
            if plugin.can_handle(intent, dimension, message):
                return plugin
        return None


# Global registry
_registry = PluginRegistry()


def register_plugin(plugin: AdvisorPlugin) -> None:
    _registry.register(plugin)


# ── Main Entry Point ─────────────────────────────────────────────────────

def generate_response(
    message: str,
    session: SessionContext | None = None,
    finding_context: dict[str, Any] | None = None,
    analysis_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a response using the AI Rapporteur.

    Returns:
        dict with keys:
          - reply: str (the response text)
          - intent: str (classified intent)
          - dimension: str | None
          - provider: str (how the response was generated)
    """
    start = time.time()

    if session is None:
        session = SessionContext()

    if finding_context:
        session.set_finding_context(finding_context)

    intent, dimension = classify_intent(message, session)
    reply: str | None = None
    provider: str = "template"

    # Try plugin handlers first
    plugin = _registry.get_handler(intent, dimension, message)
    if plugin:
        try:
            reply = plugin.handle(message, intent, dimension, session)
            if reply:
                provider = f"plugin:{plugin.name}"
        except Exception as exc:
            logger.error("advisor_plugin_failed", plugin=plugin.name, error=str(exc))

    # Fall back to built-in generators
    if reply is None:
        try:
            if intent == Intent.GREETING:
                reply = _build_greeting_response()
            elif intent == Intent.CONCEPT_EXPLANATION and dimension:
                reply = _build_concept_response(
                    dimension,
                    _get_dimension_definition(dimension),
                    _get_dimension_aspects(dimension),
                )
            elif intent == Intent.ANALYSIS_EXPLANATION and dimension:
                reply = _build_analysis_explanation(
                    dimension,
                    finding_context or session.finding_context,
                    analysis_results,
                )
            elif intent == Intent.RECOMMENDATION_EXPLANATION and dimension:
                reply = _build_recommendation_response(
                    dimension,
                    finding_context or session.finding_context,
                    analysis_results,
                )
            elif intent == Intent.EDUCATIONAL:
                reply = _build_educational_response(message, dimension)
            elif intent == Intent.GENERAL:
                # Try to find a dimension in the message even if not classified
                dim = dimension or _extract_dimension(message)
                if dim:
                    reply = _build_concept_response(
                        dim,
                        _get_dimension_definition(dim),
                        _get_dimension_aspects(dim),
                    )
                    intent = Intent.CONCEPT_EXPLANATION
                    dimension = dim
                else:
                    reply = _build_unknown_response()
            else:
                reply = _build_unknown_response()
        except Exception as exc:
            logger.error("advisor_fallback_failed", intent=intent.value, error=str(exc))
            reply = _build_unknown_response()

    # Update session
    session.update(message, reply, intent, dimension)

    logger.info(
        "advisor_response_generated",
        intent=intent.value,
        dimension=dimension,
        provider=provider,
        latency_ms=round((time.time() - start) * 1000),
    )

    return {
        "reply": reply,
        "intent": intent.value,
        "dimension": dimension,
        "provider": provider,
    }
