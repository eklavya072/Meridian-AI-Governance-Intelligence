"""How many reference instruments independently expect each mechanism.

WHY THIS EXISTS
───────────────
The 45-mechanism inventory was flat: a dimension missing "user disclosure" —
which 38 of the 43 indexed instruments name — reported the same gap as one
missing "model documentation", which 20 name. A ministry reading "you provide
4 of 6 mechanisms" cannot tell which of the two absent ones to fix first, and
that is the question they actually have.

WHY IT IS COUNTED THIS WAY, AND NOT MEASURED BY SIMILARITY
──────────────────────────────────────────────────────────
An earlier attempt scored documents by embedding their prose against framework
prose. It inverted: Japan's principles-voice guidance sits closer to framework
language than the EU AI Act's statutory phrasing, so soft law outscored hard
law. Similarity measures how a document is WRITTEN, not what it REQUIRES.

This function never reads a country document. It counts, over the reference
corpus alone, how many distinct instruments name each mechanism. A count of
independent sources agreeing is a consensus measure; it cannot import the
writing-register confound because only one side of the comparison exists.

SUSTAINED MENTION, NOT PRESENCE
───────────────────────────────
A mechanism counts for an instrument only when its vocabulary appears in at
least two separate chunks, so a single passing reference does not weigh the
same as a dedicated article. Measured against both benchmark families this is
identical to counting bare presence (+0.29 / +0.30) while being the more
defensible rule.

Weighting by HOW MUCH an instrument discusses a mechanism was also measured and
rejected: it scores mechanisms that appear in long documents, which is the
document-length bias this project has been bitten by three times, and it sent
the binding-force correlation to −0.10.
"""

from __future__ import annotations

import re
from functools import lru_cache

import structlog

logger = structlog.get_logger()

#: A mechanism must appear in at least this many chunks of an instrument before
#: that instrument counts as expecting it.
MIN_CHUNKS_PER_FRAMEWORK = 2

#: A gap is only a PRIORITY when the instruments broadly agree it matters.
#: Salience runs 1..38 over 43 instruments with a median of 19, so a mechanism
#: named by fewer than half is a minority expectation, not a consensus — and
#: listing one as a priority ("purpose limitation, expected by 1 of 43") makes
#: the whole panel look arbitrary, which is worse than showing nothing.
PRIORITY_FLOOR = 22


@lru_cache(maxsize=1)
def mechanism_salience() -> dict[str, int]:
    """Map "<dimension>|<mechanism>" to the number of instruments expecting it.

    Computed once per process from the framework corpus. Returns an empty map
    if the store is unreachable — callers treat absent salience as "unknown"
    and fall back to the flat list, so a scrape failure degrades the ordering
    rather than the verdict.
    """
    from src.evidence_strength import DIMENSION_MECHANISMS
    from src.mechanism_matching import _cue_pattern

    by_framework: dict[str, set[str]] = {}
    try:
        from src.vectorstore import iter_library_chunks, open_collection

        for text, md in iter_library_chunks(open_collection()):
            md = md or {}
            # `framework` is the key RETRIEVAL filters on and the only one
            # that matches config for all 43 instruments — the other two hold
            # filenames for 32 of them. Counting by filename happens to give
            # the right total today because each instrument is one file, but
            # an instrument split across two PDFs would be counted twice and
            # its salience halved.
            name = md.get("framework") or md.get("framework_name") or md.get("document_name")
            if not name:
                # 90 chunks carry neither name. Bucketing them under "?" made
                # them a 44th instrument that does not exist, so a mechanism
                # found only there was credited to a source nobody could cite —
                # and the count then exceeded the denominator this module's own
                # framework_count() reports.
                continue
            # A set: a framework serving two roles is indexed once per role,
            # and counting both copies let a single passing mention clear
            # MIN_CHUNKS_PER_FRAMEWORK on its own.
            by_framework.setdefault(name, set()).add(text or "")
    except Exception as exc:
        logger.warning("framework_salience_unavailable", error=str(exc))
        return {}

    salience: dict[str, int] = {}
    for dimension, table in DIMENSION_MECHANISMS.items():
        for mechanism, cues in table.items():
            pattern = re.compile("|".join(_cue_pattern(c) for c in cues), re.IGNORECASE)
            salience[f"{dimension}|{mechanism}"] = sum(
                1
                for texts in by_framework.values()
                if sum(1 for t in texts if pattern.search(t)) >= MIN_CHUNKS_PER_FRAMEWORK
            )
    logger.info(
        "framework_salience_computed",
        instruments=len(by_framework),
        mechanisms=len(salience),
    )
    return salience


@lru_cache(maxsize=1)
def framework_count() -> int:
    """How many instruments the salience was counted over.

    Counted directly. An earlier version returned the largest salience value
    as a "lower bound", which printed "expected by 31 of 39" when the corpus
    holds 43 — every ratio on screen was inflated by a denominator that was
    itself a measurement.
    """
    try:
        from src.vectorstore import iter_library_chunks, open_collection

        names = {
            (md or {}).get("framework")
            or (md or {}).get("framework_name")
            or (md or {}).get("document_name")
            for _, md in iter_library_chunks(open_collection())
        }
        return len(names - {None, ""})
    except Exception as exc:
        logger.warning("framework_count_unavailable", error=str(exc))
        return 0


def rank_absent(dimension: str, absent: list[str]) -> list[dict[str, object]]:
    """Absent mechanisms the instruments broadly agree on, most-expected first.

    Ordering and filtering only. Nothing here changes a verdict — it decides
    which gaps a reader is shown. Mechanisms below PRIORITY_FLOOR are dropped
    rather than ranked last: a minority expectation is not a priority, and
    padding the list with them invites the reader to distrust the ones above.
    """
    salience = mechanism_salience()
    rows = [{"mechanism": m, "expected_by": salience.get(f"{dimension}|{m}", 0)} for m in absent]
    return sorted(
        (r for r in rows if int(r["expected_by"]) >= PRIORITY_FLOOR),
        key=lambda row: (-int(row["expected_by"]), str(row["mechanism"])),
    )
