"""Key terms in the executive brief, marked for emphasis.

A minister skims. Each prose paragraph of the brief marks its most
decision-relevant terms with ``**...**``: a count, a verdict, a named body or
law, a dimension, a governance mechanism. The brief page renders a marked
term bold and underlined, and both exports do the same.

Marks are added when a brief is served or exported, never stored, so every
brief, old or new, is treated alike and the stored text stays exactly what
the analysis produced.
"""

from __future__ import annotations

import copy
import re
from typing import Any

_NUMBER = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)"

# Priority order: a lower number wins a place first.
_PATTERNS: list[tuple[int, re.Pattern[str]]] = [
    # Counts that carry the finding: "3 binding requirement(s)", "39 of 40".
    (
        0,
        re.compile(
            rf"\b{_NUMBER}\s+(?:binding|enforceable)\s+(?:requirement|provision|dut|obligation)\w*(?:\(s\))?",
            re.I,
        ),
    ),
    (0, re.compile(r"\b\d+\s+of\s+\d+\b")),
    (0, re.compile(r"\b\d+(?:\.\d+)?%")),
    (0, re.compile(r"\bdepth index (?:of|stands at|is) \d+(?:\.\d+)?")),
    # Verdicts.
    (1, re.compile(r"\b(?:Fully Covered|Partially Covered|Not Covered|Insufficient Evidence)\b")),
    (1, re.compile(r"\b(?:Institutionalized|Operationalized|Delegated|Emerging|Unaddressed)\b")),
    (1, re.compile(r"\b(?:Covered|Partial|Missing)\b")),
    # Named instruments and bodies.
    (2, re.compile(r"\b(?:GDPR|PIPL|APPI|DPDP|PIPA|EU AI Act|OECD|UNESCO|NIST)\b")),
    (
        2,
        re.compile(
            r"\b(?:[A-Z][A-Za-z]*\s+){1,5}"
            r"(?:Act|Bill|Law|Regulation|Commission|Commissioner|Authority|Office|"
            r"Institute|Council|Board|Agency|Ministry|Strategy|Guidelines)\b(?:\s+\d{4})?"
        ),
    ),
    # Dimensions.
    (
        3,
        re.compile(
            r"\b(?:Transparency|Accountability|Privacy|Safety|Human Autonomy|"
            r"Inclusivity|Fairness|Environmental Sustainability)\b"
        ),
    ),
    # Governance mechanisms.
    (
        4,
        re.compile(
            r"\b(?:enforcement(?: powers)?|enforceable|human oversight|oversight|redress|"
            r"sanctions|penalties|audits?|impact assessments?|conformity assessments?|"
            r"grievance|incident reporting|liability|data protection|registration|"
            r"disclosure|bias|discrimination|human rights|protected characteristics|"
            r"fairness metrics|pre-deployment testing|incident monitoring|"
            r"regulatory (?:requirements|mandates)|voluntary compliance|binding)\b",
            re.I,
        ),
    ),
]


def _limit(text: str) -> int:
    """How many terms a paragraph of this length marks."""
    n = len(text)
    if n < 60:
        return 1
    if n < 200:
        return 2
    if n < 420:
        return 3
    return 4


def emphasize(text: str) -> str:
    """Mark a paragraph's key terms with ``**``; text already marked is left
    as it is."""
    if not text or "**" in text:
        return text
    found: list[tuple[int, int, int]] = []  # (priority, start, end)
    for priority, pattern in _PATTERNS:
        found.extend((priority, m.start(), m.end()) for m in pattern.finditer(text))
    found.sort()

    # At most two terms of one kind, so a list of dimensions is not marked
    # item by item; and never half of a hyphenated word ("non-discrimination").
    chosen: list[tuple[int, int]] = []
    seen: set[str] = set()
    per_kind: dict[int, int] = {}
    for priority, start, end in found:
        term = text[start:end].lower()
        if (
            term in seen
            or per_kind.get(priority, 0) == 2
            or (start and text[start - 1] == "-")
            or any(start < e and end > s for s, e in chosen)
        ):
            continue
        chosen.append((start, end))
        seen.add(term)
        per_kind[priority] = per_kind.get(priority, 0) + 1
        if len(chosen) == _limit(text):
            break

    for start, end in sorted(chosen, reverse=True):
        text = f"{text[:start]}**{text[start:end]}**{text[end:]}"
    return text


def _paragraphs(text: str) -> str:
    return "\n\n".join(emphasize(p) for p in (text or "").split("\n\n"))


def emphasize_brief(brief: dict[str, Any]) -> dict[str, Any]:
    """A copy of the brief with the key terms of its prose marked. Quotes,
    headings, lists of names and the scope note are left as they are."""
    out = copy.deepcopy(brief)
    s = out.get("sections") or {}
    if s.get("executive_summary"):
        s["executive_summary"] = _paragraphs(s["executive_summary"])
    for key in ("areas_of_strength", "areas_requiring_attention"):
        s[key] = [emphasize(item) for item in s.get(key) or []]
    for rec in s.get("priority_recommendations") or []:
        rec["rationale"] = emphasize(rec.get("rationale") or "")
    for row in s.get("dimension_assessment") or []:
        row["basis"] = emphasize(row.get("basis") or "")
    for item in s.get("implementation_roadmap") or []:
        for phase in item.get("phases") or []:
            phase["objective"] = emphasize(phase.get("objective") or "")
    if s.get("relevant_precedent"):
        s["relevant_precedent"] = emphasize(s["relevant_precedent"])
    for p in s.get("precedents") or []:
        p["what_happened"] = emphasize(p.get("what_happened") or "")
        p["lesson"] = emphasize(p.get("lesson") or "")
    return out


_MARK = re.compile(r"\*\*(.+?)\*\*")


def split_marks(text: str) -> list[tuple[str, bool]]:
    """Text as (fragment, emphasised) pairs, for renderers that build runs."""
    parts: list[tuple[str, bool]] = []
    pos = 0
    for m in _MARK.finditer(text):
        if m.start() > pos:
            parts.append((text[pos : m.start()], False))
        parts.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        parts.append((text[pos:], False))
    return parts
