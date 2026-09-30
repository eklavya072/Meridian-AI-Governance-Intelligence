"""The deterministic reading of a golden document, and its committed snapshot.

For each governance dimension: the provisions that name it, their normative
tiers, the mechanisms the cues find, and the coverage and depth verdicts the
scorer maps them to. No model and no retrieval: the whole document is swept
(core_term_provisions, the same sweep production uses), mechanisms come from
the cues alone, and structural admission — which depends on retrieval
ranking — is left to the replay gate.

A reading is a pure function of the PDF and the scoring code, so any change in
tests/golden/expected.json is a change in how Meridian scores real
legislation. Regenerate deliberately, and read the diff:

    cd backend && uv run python -m tests.golden.reading
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
EXPECTED = HERE / "expected.json"

# file -> (document name, jurisdiction the document belongs to)
DOCUMENTS = {
    "eu-ai-act-2024-1689.pdf": ("EU AI Act", "European Union"),
    "uk-pro-innovation-ai-regulation-2023.pdf": (
        "A pro-innovation approach to AI regulation",
        "United Kingdom",
    ),
}


def read_document(filename: str) -> dict[str, Any]:
    from src.evidence_strength import (
        TIER_OBLIGATORY,
        coverage_from_profile,
        depth_from_profile,
        detect_mechanisms,
        detect_nonbinding_document,
    )
    from src.gap_analyzer import GOVERNANCE_DIMENSIONS, core_term_provisions
    from src.grading import apply_mechanism_gate, build_provision_profile, detect_enforcement_regime
    from src.ingestion import ingest_document

    name, country = DOCUMENTS[filename]
    chunks = ingest_document(HERE / filename, workspace_id="golden", document_name=name)
    texts = [c.text for c in chunks]
    voluntary = {name} if detect_nonbinding_document(texts) else set()
    with_regime = {name} if detect_enforcement_regime(texts) else set()

    dimensions: dict[str, Any] = {}
    for dimension in GOVERNANCE_DIMENSIONS:
        sentences, source_force = core_term_provisions(
            {name: texts}, dimension, voluntary, with_regime
        )
        profile = build_provision_profile(
            sentences, dimension=dimension, own_jurisdiction=country, source_force=source_force
        )
        mechanisms = detect_mechanisms(profile.sentences, dimension)
        coverage, _ = coverage_from_profile(profile, mechanisms=mechanisms)
        depth, _ = depth_from_profile(profile, document_enforcement_regime=bool(with_regime))
        bound = sum(1 for tier in mechanisms.present.values() if tier >= TIER_OBLIGATORY)
        depth, _ = apply_mechanism_gate(depth, bound)
        tiers = Counter(s.tier for s in profile.sentences if not s.excluded)
        dimensions[dimension] = {
            "coverage": coverage,
            "depth": depth,
            "scored": profile.n_scored,
            "binding": profile.n_binding,
            "enforceable": profile.n_enforceable,
            "tiers": {f"T{t}": tiers[t] for t in sorted(tiers)},
            "mechanisms_present": dict(sorted(mechanisms.present.items())),
            "mechanisms_absent": sorted(mechanisms.absent),
        }
    return {
        "chunks": len(chunks),
        "voluntary": bool(voluntary),
        "enforcement_regime": bool(with_regime),
        "dimensions": dimensions,
    }


def read_all() -> dict[str, Any]:
    return {filename: read_document(filename) for filename in sorted(DOCUMENTS)}


if __name__ == "__main__":
    EXPECTED.write_text(json.dumps(read_all(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {EXPECTED}")
