"""Executive Brief synthesis — reads the ALREADY-COMPUTED, citation-verified
analysis results stored for a workspace and compresses them into a 1-2 page
decision-maker brief. This is a synthesis task, not a re-analysis: exactly one
LLM call (the narrative sections), and every number / statistic in the brief is
assembled deterministically in code so the model can never invent one.

Sections split:
  - LLM-written (one call): executive summary, key findings (strengths /
    attention areas), priority recommendations.
  - Deterministic (code, from stored data): header, risk overview, relevant
    precedent (from Module 4 matches), scope & methodology (reuses the stored
    scope disclaimer verbatim).
"""

from __future__ import annotations

import structlog
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from src.provider_router import get_provider, generate_with_retry

logger = structlog.get_logger()

PRIORITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, None: 9}


# ── LLM-written narrative schema ──────────────────────────────────────────

class BriefPriorityRecommendation(BaseModel):
    """One selected recommendation with a one-line rationale. Both fields are
    drawn ONLY from the digest — the model compresses, never invents."""

    recommendation: str = Field(..., description="One sentence, from the digest only")
    rationale: str = Field(..., description="One line, from the digest only")


class BriefSynthesis(BaseModel):
    """The ONLY LLM-generated part of the brief.

    Fields are deliberately permissive (lists may be empty) so a validation
    failure can never force a retry loop — empties are rendered honestly
    ("None identified") by the assembly code.
    """

    executive_summary: str = Field(
        ..., description="2-4 sentences, max 80 words, synthesizing the digest"
    )
    areas_of_strength: list[str] = Field(
        default_factory=list, description="2-3 bullets, each max 40 words"
    )
    areas_requiring_attention: list[str] = Field(
        default_factory=list,
        description="Up to 3 bullets, each max 40 words. Empty when every dimension is fully covered.",
    )
    priority_recommendations: list[BriefPriorityRecommendation] = Field(
        default_factory=list,
        description="3-5 items from the highest-priority gapped dimensions only. Empty when no gaps.",
    )


BRIEF_SYSTEM_PROMPT = (
    "You are an executive brief writer for AI governance assessments. You are "
    "given the already-computed, citation-verified results of a governance gap "
    "analysis. Your ONLY job is to synthesize and compress that material into a "
    "decision-maker-ready narrative.\n\n"
    "STRICT RULES (anti-fabrication — the same discipline as the rest of this project):\n"
    "1. You may only restate, compress, and re-order information present in the DIGEST.\n"
    "2. You must NOT introduce: new numbers, new dimensions, new framework names, new "
    "recommendations, or new claims of any kind.\n"
    "3. If a section has little material (e.g. no Partial/Missing dimensions), write it "
    "honestly short. Never pad with generic filler to hit a length target.\n"
    "4. Do not copy recommendation text verbatim — compress it into your own words while "
    "keeping every substantive element.\n"
    "5. Tone: precise, neutral, decision-maker oriented. No marketing language.\n\n"
    "PER-SECTION WORD BUDGETS (enforce exactly):\n"
    "- executive_summary: 2-4 sentences, max 80 words total.\n"
    "- areas_of_strength: 2-3 bullets, each max 40 words, one per finding.\n"
    "- areas_requiring_attention: up to 3 bullets, each max 40 words. If every dimension "
    "is fully covered, return an empty list.\n"
    "- priority_recommendations: 3-5 items total, selected from the highest-priority "
    "gapped dimensions only. Each recommendation is one sentence; each rationale is one "
    "line drawn from the digest. If there are no gapped dimensions, return an empty list."
)


# ── Digest builders (compact, prompt-budget-friendly) ─────────────────────

def build_dimension_digest(gaps: list[dict[str, Any]]) -> str:
    """Compress each dimension's stored verdict into a few lines. The LLM's
    only allowed source of facts — every claim here was already computed and
    citation-verified during the analysis run."""
    lines: list[str] = []
    for g in gaps:
        dim = g.get("dimension") or "Unknown"
        coverage = g.get("coverage") or "Unknown"
        lines.append(f"- {dim}: Coverage {coverage}")
        m1 = g.get("module_1") or {}
        if m1.get("governance_maturity"):
            lines.append(f"  Maturity: {m1['governance_maturity']}")
        m2 = g.get("module_2") or {}
        if m2.get("priority"):
            lines.append(f"  Priority: {m2['priority']}")
        recs = [r for r in (m2.get("recommendations") or []) if r]
        if recs:
            lines.append("  Recommendations (from the analysis):")
            for r in recs[:3]:
                lines.append(f"    - {r}")
        elif coverage == "Covered":
            bp = m2.get("best_practices") or {}
            opps = [o for o in (bp.get("future_strengthening_opportunities") or []) if o]
            if opps:
                lines.append("  Fully covered — future strengthening opportunities:")
                for o in opps[:2]:
                    lines.append(f"    - {o}")
        if g.get("analysis_error"):
            lines.append(f"  [Not analysed — {str(g['analysis_error'])[:100]}]")
    return "\n".join(lines) if lines else "(no dimension results available)"


def build_brief_prompt(
    digest: str,
    decision: dict[str, Any] | None,
    num_dimensions: int,
) -> str:
    parts: list[str] = []
    parts.append("=== GOVERNANCE ANALYSIS DIGEST (the ONLY allowed source of facts) ===")
    parts.append(digest)
    parts.append("")
    parts.append("=== EXECUTIVE AGGREGATES (computed by the analysis — use them as-is) ===")
    if decision:
        parts.append(f"Assessed dimensions: {decision.get('assessed_dimensions', num_dimensions)}")
        parts.append(f"Coverage distribution: {decision.get('covered', 0)} Covered, "
                     f"{decision.get('partial', 0)} Partial, "
                     f"{decision.get('missing', 0)} Missing")
        parts.append(f"Overall governance maturity (weakest-dimension rule): "
                     f"{decision.get('overall_governance_maturity', 'n/a')}")
        strongest = decision.get("strongest_dimension")
        if strongest:
            parts.append(f"Strongest dimension: {strongest}")
        prio = decision.get("highest_priority_dimensions") or []
        if prio:
            parts.append(f"Highest-priority dimensions: {', '.join(prio)}")
    else:
        parts.append(f"Assessed dimensions: {num_dimensions}")
    parts.append("")
    parts.append(
        "Write the executive brief now. Return ONLY the JSON object matching the schema."
    )
    return "\n".join(parts)


# ── Deterministic sections (code-computed, never LLM) ─────────────────────

def build_risk_overview(
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Risk distribution + priority dimensions, assembled from stored data.

    A small table/paragraph: distribution by risk level, which dimensions
    carry High/Critical priority, and one sentence on compounding risk when
    multiple high-priority dimensions share a cluster.
    """
    distribution: dict[str, int] = {
        "High": 0, "Medium": 0, "Low": 0, "Insufficient Evidence": 0,
    }
    for g in gaps:
        rl = g.get("risk_level")
        if rl in distribution:
            distribution[rl] += 1
        else:
            distribution.setdefault(rl or "Insufficient Evidence", 0)
            distribution[rl or "Insufficient Evidence"] += 1

    priority_dims: list[tuple[str, str]] = []
    for g in gaps:
        m2 = g.get("module_2") or {}
        p = m2.get("priority")
        if p in ("Critical", "High"):
            priority_dims.append((g.get("dimension") or "Unknown", p))
    priority_dims.sort(key=lambda x: PRIORITY_RANK.get(x[1], 9))
    high_priority_dimensions = [d for d, _ in priority_dims]

    assessed = len(gaps)
    para = f"The analysis assessed {assessed} dimension(s). Risk distribution: " \
           f"{distribution['High']} High, {distribution['Medium']} Medium, " \
           f"{distribution['Low']} Low, {distribution['Insufficient Evidence']} " \
           "Insufficient Evidence."
    if high_priority_dimensions:
        para += f" High-priority dimensions: {', '.join(high_priority_dimensions)}."
    if len(high_priority_dimensions) >= 2:
        para += (
            " Multiple dimensions share the highest priority — compounding risk "
            "across these dimensions raises the urgency of coordinated, sequenced "
            "implementation."
        )
    elif high_priority_dimensions:
        para += (
            " Single highest-priority dimension — sequencing should begin there "
            "before related clusters are addressed."
        )

    return {
        "paragraph": para,
        "high_priority_dimensions": high_priority_dimensions,
        "distribution": distribution,
    }


def build_relevant_precedent(gaps: list[dict[str, Any]]) -> str | None:
    """1-2 sentence note on matched Module 4 incidents (illustrative context
    only — never the full case-study treatment). Deterministic: reads the
    already-verified incident matches."""
    incident_names: list[str] = []
    for g in gaps:
        m4 = g.get("module_4") or {}
        for inc in (m4.get("incident_matches") or []):
            name = (inc.get("incident_name") or "").strip()
            if name and name not in incident_names:
                incident_names.append(name)
    if not incident_names:
        return None
    if len(incident_names) == 1:
        return (
            f"The analysis matched one real-world incident as illustrative "
            f"context ({incident_names[0]}); the full report carries the "
            "case-study detail."
        )
    return (
        f"The analysis matched {len(incident_names)} real-world incidents as "
        f"illustrative context ({', '.join(incident_names)}); the full report "
        "carries the case-study detail."
    )


def build_scope_and_methodology(
    scope_disclaimer: str,
    frameworks_used: list[str],
    documents: list[str],
    num_dimensions: int,
) -> str:
    """Scope & Methodology — the stored scope disclaimer verbatim (never
    regenerated) plus a one-line note on sources and frameworks."""
    parts = [scope_disclaimer]
    fw_line = (
        f"This brief synthesizes the already-computed analysis of "
        f"{num_dimensions} governance dimensions evaluated against "
        f"{len(frameworks_used)} reference framework(s): "
        f"{', '.join(frameworks_used) if frameworks_used else 'the configured core frameworks'}."
    )
    parts.append(fw_line)
    if documents:
        parts.append("Source input(s): " + ", ".join(documents) + ".")
    return "\n\n".join(parts)


# ── Assembly + orchestration ──────────────────────────────────────────────

def assemble_brief(
    *,
    workspace_id: str,
    country: str,
    policy_title: str,
    document_name: str,
    documents: list[str],
    frameworks_used: list[str],
    scope_disclaimer: str,
    gaps: list[dict[str, Any]],
    synthesis: BriefSynthesis,
    decision_analytics: dict[str, Any] | None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compose the full structured brief from LLM narrative + deterministic
    sections. This exact dict is what gets persisted (reports.meta) and what
    both exporters (DOCX/PDF) and the frontend render from."""
    if not generated_at:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    coverage_summary = {
        "covered": sum(1 for g in gaps if g.get("coverage") == "Covered"),
        "partial": sum(1 for g in gaps if g.get("coverage") == "Partial"),
        "missing": sum(1 for g in gaps if g.get("coverage") == "Missing"),
        "insufficient_evidence": sum(
            1 for g in gaps if g.get("coverage") == "Insufficient Evidence"
        ),
        "analysis_failed": sum(1 for g in gaps if g.get("analysis_error")),
    }
    risk_overview = build_risk_overview(gaps)
    precedent = build_relevant_precedent(gaps)
    scope_and_methodology = build_scope_and_methodology(
        scope_disclaimer=scope_disclaimer,
        frameworks_used=frameworks_used,
        documents=documents,
        num_dimensions=len(gaps),
    )

    return {
        "workspace_id": workspace_id,
        "country": country,
        "policy_title": policy_title,
        "document_name": document_name,
        "documents": documents,
        "generated_at": generated_at,
        "num_dimensions": len(gaps),
        "frameworks_used": frameworks_used,
        "scope_disclaimer": scope_disclaimer,
        "coverage_summary": coverage_summary,
        "sections": {
            "executive_summary": (synthesis.executive_summary or "").strip(),
            "areas_of_strength": [s.strip() for s in synthesis.areas_of_strength if s.strip()],
            "areas_requiring_attention": [
                s.strip() for s in synthesis.areas_requiring_attention if s.strip()
            ],
            "risk_overview": risk_overview,
            "priority_recommendations": [
                {
                    "recommendation": r.recommendation.strip(),
                    "rationale": r.rationale.strip(),
                }
                for r in synthesis.priority_recommendations
                if r.recommendation.strip()
            ],
            "relevant_precedent": precedent,
            "scope_and_methodology": scope_and_methodology,
        },
        # Deterministic analytics for dashboards / research (same shape as
        # decision_analytics so downstream consumers can reuse it).
        "decision_analytics": decision_analytics or {},
    }


def generate_brief(
    *,
    workspace_id: str,
    country: str,
    policy_title: str,
    document_name: str,
    documents: list[str],
    frameworks_used: list[str],
    scope_disclaimer: str,
    gaps: list[dict[str, Any]],
    decision_analytics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the ONE synthesis call and assemble the brief.

    Routes through the shared provider abstraction (Gemini primary with key
    rotation + Groq fallback, RPD/RPM throttling) exactly like analysis calls —
    this call is never a separate, unguarded path.
    """
    provider = get_provider()
    digest = build_dimension_digest(gaps)
    prompt = build_brief_prompt(
        digest=digest,
        decision=decision_analytics,
        num_dimensions=len(gaps),
    )
    synthesis = generate_with_retry(
        provider=provider,
        prompt=prompt,
        schema=BriefSynthesis,
        system_prompt=BRIEF_SYSTEM_PROMPT,
        operation="brief_synthesis",
    )

    brief = assemble_brief(
        workspace_id=workspace_id,
        country=country,
        policy_title=policy_title,
        document_name=document_name,
        documents=documents,
        frameworks_used=frameworks_used,
        scope_disclaimer=scope_disclaimer,
        gaps=gaps,
        synthesis=synthesis,
        decision_analytics=decision_analytics,
    )

    logger.info(
        "brief_synthesis_complete",
        workspace_id=workspace_id,
        document_name=document_name,
        num_dimensions=len(gaps),
        summary_chars=len(brief["sections"]["executive_summary"]),
        strengths=len(brief["sections"]["areas_of_strength"]),
        attention=len(brief["sections"]["areas_requiring_attention"]),
        recommendations=len(brief["sections"]["priority_recommendations"]),
        precedent=bool(brief["sections"]["relevant_precedent"]),
        provider=provider.model_name,
    )
    return brief


def render_brief_markdown(brief: dict[str, Any]) -> str:
    """Plain-text/markdown rendering of the structured brief — stored in
    reports.content as a readable fallback (the DOCX/PDF exporters build from
    the structured dict, not this string)."""
    s = brief["sections"]
    lines: list[str] = []
    lines.append(f"# {brief['country']} — {brief['policy_title']}")
    lines.append("AI Governance Assessment Brief")
    lines.append(
        f"Generated {brief['generated_at']} · Based on analysis of "
        f"{brief['num_dimensions']} governance dimensions"
    )
    lines.append("")
    lines.append("## EXECUTIVE SUMMARY")
    lines.append(s["executive_summary"])
    lines.append("")
    lines.append("## KEY FINDINGS")
    lines.append("### Areas of Strength")
    if s["areas_of_strength"]:
        lines.extend(f"- {b}" for b in s["areas_of_strength"])
    else:
        lines.append("- None identified.")
    lines.append("### Areas Requiring Attention")
    if s["areas_requiring_attention"]:
        lines.extend(f"- {b}" for b in s["areas_requiring_attention"])
    else:
        lines.append("- None identified.")
    lines.append("")
    lines.append("## RISK OVERVIEW")
    lines.append(s["risk_overview"]["paragraph"])
    lines.append("")
    lines.append("## PRIORITY RECOMMENDATIONS")
    recs = s["priority_recommendations"]
    if recs:
        for i, r in enumerate(recs, 1):
            lines.append(f"{i}. **{r['recommendation']}** — {r['rationale']}")
    else:
        lines.append("No critical gaps identified — no priority actions required.")
    if s.get("relevant_precedent"):
        lines.append("")
        lines.append("## RELEVANT PRECEDENT")
        lines.append(s["relevant_precedent"])
    lines.append("")
    lines.append("## SCOPE & METHODOLOGY")
    lines.append(s["scope_and_methodology"])
    lines.append("")
    return "\n".join(lines)
