from __future__ import annotations

from datetime import datetime

import structlog

from src.gap_analyzer import GapAnalysisResult, RiskLevel

logger = structlog.get_logger()


def generate_executive_brief_text(
    result: GapAnalysisResult,
) -> str:
    sections: list[str] = []

    sections.append("=" * 72)
    sections.append("EXECUTIVE BRIEF — AI Policy Gap Analysis")
    sections.append("=" * 72)
    sections.append("")
    sections.append(f"Document analyzed: {result.document_name}")
    sections.append(f"Analysis ID: {result.analysis_id}")
    sections.append(f"Date: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    sections.append(f"Frameworks used: {', '.join(result.frameworks_used)}")
    sections.append("")

    sections.append("-" * 72)
    sections.append("1. EXECUTIVE SUMMARY")
    sections.append("-" * 72)
    sections.append(result.summary)
    sections.append("")

    sections.append("-" * 72)
    sections.append("2. KEY FINDINGS BY GOVERNANCE DIMENSION")
    sections.append("-" * 72)
    sections.append("")

    logger.info(
        "stage_8_report_generation_started",
        document_name=result.document_name,
        analysis_id=result.analysis_id,
        num_dimensions=len(result.governance_gaps),
        frameworks_used=result.frameworks_used,
    )

    for gap in result.governance_gaps:
        risk_tag = f"[{gap.risk_level.value}]" if gap.risk_level else "[Insufficient Evidence]"
        sections.append(f"  {risk_tag} {gap.dimension}")
        sections.append(f"  {'─' * 40}")

        coverage_tag = gap.coverage.value if gap.coverage else "Unknown"
        sections.append(f"  Coverage: {coverage_tag}")

        if gap.gap_analysis:
            for line in gap.gap_analysis.split("\n"):
                if line.strip():
                    sections.append(f"  {line}")
        else:
            sections.append(f"  Gap identified: {'Yes' if gap.gap_found else 'No'}")
            # Fully Covered tier: reason_flagged may be empty (nothing was
            # flagged) — don't emit an empty 'Assessment:' line.
            if gap.reason_flagged:
                sections.append(f"  Assessment: {gap.reason_flagged}")

        if gap.risk_level and gap.risk_level != RiskLevel.INSUFFICIENT_EVIDENCE:
            sections.append(f"  Risk: {gap.risk_reason}")
            if gap.potential_consequence:
                sections.append(f"  Consequence: {gap.potential_consequence}")

        if gap.recommendation:
            sections.append(f"  Recommendation: {gap.recommendation}")
        if gap.un_recommendation:
            sections.append(f"  Smallest Effective Improvement: {gap.un_recommendation}")
        sections.append("")

    sections.append("-" * 72)
    sections.append("3. RISK SUMMARY")
    sections.append("-" * 72)
    high_risk = [g for g in result.governance_gaps if g.risk_level == RiskLevel.HIGH]
    med_risk = [g for g in result.governance_gaps if g.risk_level == RiskLevel.MEDIUM]
    low_risk = [g for g in result.governance_gaps if g.risk_level == RiskLevel.LOW]
    insufficient = [
        g for g in result.governance_gaps if g.risk_level == RiskLevel.INSUFFICIENT_EVIDENCE
    ]

    sections.append(
        f"  High Risk: {len(high_risk)} — {', '.join(g.dimension for g in high_risk) if high_risk else 'None'}"
    )
    sections.append(
        f"  Medium Risk: {len(med_risk)} — {', '.join(g.dimension for g in med_risk) if med_risk else 'None'}"
    )
    sections.append(
        f"  Low Risk: {len(low_risk)} — {', '.join(g.dimension for g in low_risk) if low_risk else 'None'}"
    )
    sections.append(
        f"  Insufficient Evidence: {len(insufficient)} — {', '.join(g.dimension for g in insufficient) if insufficient else 'None'}"
    )
    sections.append("")

    sections.append("-" * 72)
    sections.append("4. RECOMMENDATIONS")
    sections.append("-" * 72)
    sections.append("")
    for i, gap in enumerate(result.governance_gaps, 1):
        if gap.gap_found:
            rec_text = gap.un_recommendation or gap.recommendation
            sections.append(f"  {i}. {gap.dimension}: {rec_text}")

    sections.append("")
    sections.append("-" * 72)
    sections.append("5. REFERENCES")
    sections.append("-" * 72)
    sections.append("")
    sections.append("  Reference frameworks consulted:")
    for fw in result.frameworks_used:
        sections.append(f"    - {fw}")
    sections.append("")
    sections.append(f"  Retrieved evidence chunks: {result.total_retrieved}")
    sections.append(f"  Processing time: {result.total_processing_time:.2f}s")
    sections.append("=" * 72)

    brief_text = "\n".join(sections)

    logger.info(
        "stage_8_report_generation_complete",
        document_name=result.document_name,
        analysis_id=result.analysis_id,
        brief_length=len(brief_text),
        num_sections=5,
        report_structure=[
            "Executive Summary",
            "Key Findings",
            "Risk Summary",
            "Recommendations",
            "References",
        ],
    )

    return brief_text
