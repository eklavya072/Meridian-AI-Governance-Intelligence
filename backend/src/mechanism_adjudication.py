"""Decide which cue match actually establishes a mechanism, or that none does.

WHY THIS EXISTS
───────────────
`detect_mechanisms` keeps, per mechanism, the HIGHEST-TIER sentence matching
its cues. The cues are deliberately loose ("testing", "evaluat", "continuous",
"disclos"), so over a large corpus that combination reliably selects a penalty
or enforcement clause that merely contains the keyword.

Audited over four countries and three dimensions, 55 cue matches: 13 pointed
at a provision that actually establishes the mechanism. 23%. Of the 35 scored
as BOUND — the count the mechanism gate reads — 7 were right. 20%.

The damage is not mainly to the score. A mechanism wrongly marked present is
a gap that DISAPPEARS from the priority-gaps panel, so Kenya reported nothing
missing on Transparency while its cue matches were a Public Service Commission
complaints provision and "the Office shall have all powers necessary".

WHAT THIS DOES, AND WHAT IT DELIBERATELY DOES NOT
─────────────────────────────────────────────────
Cues propose candidates, a model picks one or abstains, and the EXISTING rules
score whatever it picked. The model never sees a tier, never sets one, and
never touches a threshold. It answers one question — "does this provision
establish this mechanism?" — and hands a sentence back.

That split is the point. The embedding attempt failed because per-sentence
argmax cannot say "none of these", so every sentence voted for something and
11% of the matches had topical support. Abstention is the whole value here.

FAILURE IS RECORDED, NOT HIDDEN
───────────────────────────────
Any error that survives the router's retries returns the cue result untouched,
so adjudication can never make a run fail. It is not free, though. The cue
result over-reports what is present, and the mechanism gate reads presence
downward-only, so a run that fell back can report MORE depth than one that
did not. Every dimension therefore carries `adjudication` — APPLIED or
UNAVAILABLE — and a run where it was unavailable is treated as provisional
rather than complete.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()

#: Off returns the cue result unchanged.
ENABLED = os.getenv("MECHANISM_ADJUDICATION", "1").strip() not in {"0", "false", "no"}

#: What happened to a dimension's mechanisms. Empty means adjudication was never
#: attempted (switched off, or nothing was present to judge).
APPLIED = "applied"
UNAVAILABLE = "unavailable"

#: Candidates offered per mechanism. The cue pass keeps only its top-tier hit;
#: several are needed for the model to have a real choice, and the right one is
#: often NOT the most forceful — Art. 11 "technical documentation shall be
#: drawn up" loses a tier contest to any clause mentioning fines.
CANDIDATES_PER_MECHANISM = 8

_SYSTEM = """For each MECHANISM below you are given candidate provisions from one national
governance document. One job: pick the candidate that actually ESTABLISHES that
mechanism — creates it, requires it, or operates it.

If none establishes it, return 0. A provision that merely contains a related
word, that enforces OTHER obligations, or that is background, recital or
aspiration does NOT establish the mechanism. Returning 0 is correct and
expected when the candidates are all incidental.

Mechanisms are grouped under the governance dimension they belong to. Judge
each against ITS OWN dimension: a logging duty establishes an audit trail for
Transparency, not incident monitoring for Safety.

Answer every numbered mechanism, in order: "m" is its number and "pick" is the
candidate that establishes it, or 0."""


class _Pick(BaseModel):
    m: int
    pick: int


class _Picks(BaseModel):
    picks: list[_Pick]


#: Words the PDF extractor breaks across a line: "shal l maintain", "s hall".
#: The cue matcher already tolerates this through ocr_flexible_fragment, which
#: is why the cue pass FINDS these provisions — but the model is handed raw
#: text, read "shal l" as two tokens and did not see a duty. Measured here the
#: damage is now rare (5 of 1,562 "shall") and all five sit in Kenya's AI Bill;
#: two are the public-register provision the adjudicator wrongly rejected.
#:
#: Repaired ONLY in the text shown to the model. The citation still quotes the
#: original, so verbatim verification against the source is unaffected.
#:
#: Scanning per target word rather than pairing adjacent tokens: a generic
#: "word + short fragment" rule matches greedily from the left, so in
#: "system s hall" it pairs "system"+"s" and never reaches "s"+"hall".
_REPAIR_WORDS = (
    "shall",
    "must",
    "should",
    "maintain",
    "publish",
    "register",
    "registry",
    "disclose",
    "provider",
    "providers",
    "deployer",
    "deployers",
)


@lru_cache(maxsize=1)
def _repair_patterns() -> tuple[tuple[re.Pattern[str], str], ...]:
    from src.utils import ocr_flexible_fragment

    return tuple(
        (re.compile(r"\b" + ocr_flexible_fragment(w) + r"\b", re.IGNORECASE), w)
        for w in _REPAIR_WORDS
    )


def _repair_split_words(text: str) -> str:
    """Rejoin the governance words a PDF line break split apart."""
    for pattern, whole in _repair_patterns():
        text = pattern.sub(lambda m, w=whole: w if " " in m.group(0) else m.group(0), text)
    return text


def _rank_candidates(sentences: list[Any], pattern: re.Pattern[str]) -> list[Any]:
    """Cue hits worth offering, most specific first.

    NOT by tier. Ranking by force is the same bias that produced the problem:
    it puts the penalty clause at the top of every list. Ranking by how much of
    the sentence is the cue match favours a provision ABOUT the mechanism over
    a long clause that mentions it in passing.
    """
    scored = []
    for s in sentences:
        text = getattr(s, "text", "") or ""
        hits = pattern.findall(text)
        if not hits:
            continue
        matched = sum(len(h if isinstance(h, str) else "".join(h)) for h in hits)
        density = matched / max(len(text), 1)
        scored.append((density, s))
    scored.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for _, s in scored:
        key = (getattr(s, "text", "") or "")[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= CANDIDATES_PER_MECHANISM:
            break
    return out


def adjudicate_batch(
    requests: dict[str, tuple[Any, list[Any]]],
    provider: Any,
) -> dict[str, Any]:
    """Adjudicate every dimension in ONE call.

    `requests` maps dimension -> (cue result, that dimension's sentences).
    Returns dimension -> adjudicated result. A dimension missing from the
    reply, or a total failure, keeps its cue result untouched.

    The saving is the point: eight calls per country became one, which is the
    difference between three countries a day and five on the free tier.
    """
    out = {dim: cue for dim, (cue, _) in requests.items()}
    if not ENABLED or provider is None or not requests:
        return out

    try:
        from src.evidence_strength import DIMENSION_MECHANISMS
        from src.mechanism_matching import _cue_pattern

        # Flat numbering across dimensions — the model answers one list, and
        # each entry is mapped back to its (dimension, mechanism) here.
        slots: list[tuple[str, str, list[Any]]] = []
        blocks: list[str] = []
        for dim, (cue, sentences) in requests.items():
            table = DIMENSION_MECHANISMS.get(dim) or {}
            lines: list[str] = []
            for name in getattr(cue, "present", {}) or {}:
                cues = table.get(name)
                if not cues:
                    continue
                pattern = re.compile("|".join(_cue_pattern(c) for c in cues), re.IGNORECASE)
                picked = _rank_candidates(sentences, pattern)
                if not picked:
                    continue
                slots.append((dim, name, picked))
                opts = "\n".join(
                    f'     {j}. "{_repair_split_words(getattr(s, "text", "") or "")[:230]}"'
                    for j, s in enumerate(picked, 1)
                )
                lines.append(f"{len(slots)}. MECHANISM: {name}\n{opts}")
            if lines:
                blocks.append(f"── DIMENSION: {dim} ──\n" + "\n\n".join(lines))
        if not slots:
            return out

        # Through the router, not straight to the provider. This is the one
        # model call whose answer reaches the verdict, and it used to be the
        # least protected call in the run: one attempt on one credential, no
        # throttle, no quota accounting — while the prose calls around it got
        # five retries across every key. A 503 spike therefore dropped it far
        # more often than anything else, and dropped it silently.
        from src.provider_router import generate_with_retry

        reply = generate_with_retry(
            provider=provider,
            prompt="\n\n".join(blocks),
            schema=_Picks,
            system_prompt=_SYSTEM,
            operation="mechanism_adjudication",
        )
        picks = {int(p.m): int(p.pick or 0) for p in reply.picks}
    except Exception as exc:
        logger.warning("mechanism_adjudication_failed", error=str(exc))
        for cue in out.values():
            cue.adjudication = UNAVAILABLE
        return out

    judged: dict[str, dict[str, int]] = {}
    rejected: dict[str, list[str]] = {}
    for i, (dim, name, picked) in enumerate(slots, 1):
        idx = picks.get(i, 0)
        if idx and 1 <= idx <= len(picked):
            judged.setdefault(dim, {})[name] = int(getattr(picked[idx - 1], "tier", 0) or 0)
        else:
            rejected.setdefault(dim, []).append(name)

    for dim, (cue, _) in requests.items():
        kept = judged.get(dim, {})
        dropped = rejected.get(dim, [])
        if not kept and not dropped:
            continue  # this dimension had no candidates; cue result stands
        cue.adjudication = APPLIED
        # A mechanism with no candidates was never the model's to judge.
        for name, tier in (getattr(cue, "present", {}) or {}).items():
            if name not in kept and name not in dropped:
                kept[name] = tier
        cue.present = kept
        cue.absent = sorted(set(list(getattr(cue, "absent", []) or []) + dropped))
        out[dim] = cue

    logger.info(
        "mechanism_adjudication_applied",
        calls=1,
        dimensions=len(requests),
        mechanisms=len(slots),
        rejected=sum(len(v) for v in rejected.values()),
    )
    return out
