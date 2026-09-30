"""Tier-2 evidence gate: the replay gate's analysis, against the live model.

The replay gate proves the pipeline handles the answers it recorded. This
proves the model still gives answers the pipeline can handle: one run of the
same synthetic two-article policy, live, with the same invariants. It is the
only test that spends quota, so it is off unless MERIDIAN_LIVE_GATE=1, runs
once per session, and is capped at LIVE_REQUEST_CAP model requests — a run
makes ten.

    MERIDIAN_LIVE_GATE=1 uv run pytest tests/live -q
"""

from __future__ import annotations

import os

import pytest

from src.gap_analyzer import GapAnalyzer
from src.llm_provider import GeminiProvider
from tests.unit.test_pipeline_replay import CHUNKS, FakeVectorStore, _run

LIVE_REQUEST_CAP = 12

pytestmark = pytest.mark.skipif(
    os.getenv("MERIDIAN_LIVE_GATE") != "1" or not os.getenv("GEMINI_API_KEY"),
    reason="live gate: set MERIDIAN_LIVE_GATE=1 and GEMINI_API_KEY",
)


class CappedProvider(GeminiProvider):
    """The live provider, refusing to make more than LIVE_REQUEST_CAP requests."""

    def __init__(self) -> None:
        super().__init__()
        self.requests = 0

    def generate_structured(self, prompt, schema, system_prompt=None, **kw):
        self.requests += 1
        if self.requests > LIVE_REQUEST_CAP:
            raise RuntimeError(f"live gate request cap ({LIVE_REQUEST_CAP}) reached")
        return super().generate_structured(prompt, schema, system_prompt=system_prompt, **kw)

    def generate_text(self, prompt, system_prompt=None, **kw):
        raise RuntimeError("the analysis path makes no free-text calls")


@pytest.fixture(scope="module")
def live_run():
    provider = CappedProvider()
    store = FakeVectorStore()
    result = _run(GapAnalyzer(vector_store=store, provider=provider))
    return result, store, provider


def test_the_run_stays_within_the_request_cap(live_run):
    _, _, provider = live_run
    assert 0 < provider.requests <= LIVE_REQUEST_CAP


def test_every_dimension_is_assessed(live_run):
    result, _, _ = live_run
    assert len(result.governance_gaps) == 8
    assert not [g.dimension for g in result.governance_gaps if g.analysis_error]


def test_every_citation_resolves_to_a_real_chunk(live_run):
    result, store, _ = live_run
    for gap in result.governance_gaps:
        for ev in gap.evidence:
            assert store.chunk_exists(ev.chunk_id), (gap.dimension, ev.chunk_id)


def test_no_evidence_item_is_empty(live_run):
    result, _, _ = live_run
    for gap in result.governance_gaps:
        for ev in gap.evidence:
            assert ev.text.strip()


def test_the_model_still_cites_the_document(live_run):
    # Live answers that stopped citing anything would pass every invariant
    # above trivially. The two articles are cited today; losing that is drift.
    result, _, _ = live_run
    cited = {ev.chunk_id for g in result.governance_gaps for ev in g.evidence}
    assert cited & {c["chunk_id"] for c in CHUNKS}


def test_no_chunk_id_is_rendered_as_a_provision(live_run):
    result, _, _ = live_run
    for gap in result.governance_gaps:
        prose = " ".join(
            [gap.coverage_reasoning or "", gap.reason_flagged or "", gap.framework_synthesis or ""]
        )
        for chunk in CHUNKS:
            assert chunk["chunk_id"] not in prose
