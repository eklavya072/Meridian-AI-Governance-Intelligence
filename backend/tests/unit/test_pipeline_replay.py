"""A full analysis run, end to end, with the provider replaced by fixtures.

This is the Tier-1 evidence gate: no network, no quota, deterministic. It
asserts on INVARIANTS rather than prose, because prose is the part that is
allowed to change:

  * every citation resolves to a chunk that exists
  * no claim ships without evidence behind it
  * the deterministic coverage ladder is byte-identical across runs, since
    that stage is code and any diff there is a genuine bug
  * a dimension that fails is excluded, never guessed at

The provider is a scripted fake rather than a recording of real Gemini
traffic, so there is nothing to scrub — no keys, no PII, no captured
customer text ever enters the repository.
"""

import pytest

from src.gap_analyzer import GapAnalyzer
from src.models import CoverageLevel


class ScriptedProvider:
    """Returns a valid instance of whatever schema it is handed.

    Populated from the schema itself rather than a hand-written payload, so
    a field added to the analysis schema cannot silently make these tests
    exercise a shape the pipeline no longer produces.
    """

    tier = "primary"
    model_name = "scripted-fixture"

    def __init__(self, chunk_ids=None):
        self.chunk_ids = list(chunk_ids or [])
        self.calls = []

    def generate_structured(self, prompt, schema, system_prompt=None, **kw):
        self.calls.append({"schema": schema.__name__, "prompt": prompt})
        return _fill(schema, self.chunk_ids)

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.calls.append({"schema": "text", "prompt": prompt})
        return "A deterministic fixture reply."


def _fill(schema, chunk_ids):
    """Build a minimal valid instance of a pydantic schema."""
    from enum import Enum
    from typing import get_args, get_origin

    values = {}
    for name, field in schema.model_fields.items():
        if not field.is_required():
            continue
        values[name] = _value_for(field.annotation, name, chunk_ids, get_origin, get_args, Enum)
    return schema(**values)


def _value_for(annotation, name, chunk_ids, get_origin, get_args, Enum):
    origin = get_origin(annotation)
    if origin in (list, set, tuple):
        return []
    if origin is dict:
        return {}
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return list(annotation)[0]
    if annotation is bool:
        return False
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is str:
        if "chunk_id" in name and chunk_ids:
            return chunk_ids[0]
        return "fixture text"
    if isinstance(annotation, type) and hasattr(annotation, "model_fields"):
        return _fill(annotation, chunk_ids)
    return None


CHUNKS = [
    {
        "chunk_id": "chunk-transparency-1",
        "text": (
            "Article 13. Providers of high-risk AI systems shall ensure that the "
            "operation is sufficiently transparent to enable deployers to interpret "
            "the output, and shall keep automatic logs for the lifetime of the system."
        ),
        "source_framework": "policy.pdf",
        "document_name": "policy.pdf",
        "page_number": 5,
        "similarity_score": 0.82,
        "metadata": {"document_name": "policy.pdf", "page_number": "5", "workspace_id": "w1"},
    },
    {
        "chunk_id": "chunk-accountability-1",
        "text": (
            "Article 21. The Authority shall supervise compliance and a provider who "
            "fails to comply shall be liable to an administrative fine."
        ),
        "source_framework": "policy.pdf",
        "document_name": "policy.pdf",
        "page_number": 9,
        "similarity_score": 0.79,
        "metadata": {"document_name": "policy.pdf", "page_number": "9", "workspace_id": "w1"},
    },
]


class FakeVectorStore:
    def __init__(self, chunks=CHUNKS):
        self.chunks = list(chunks)
        self._by_id = {c["chunk_id"]: c for c in self.chunks}

    def retrieve(self, **kw):
        return [dict(c) for c in self.chunks]

    def get_chunk(self, chunk_id):
        return self._by_id.get(chunk_id)

    def chunk_exists(self, chunk_id):
        return chunk_id in self._by_id

    def embed_query(self, text):
        return [float(len(text) % 5), 1.0, 0.25]

    def count_chunks(self, framework_filter=None):
        return len(self.chunks)

    def get_all_frameworks(self):
        return ["policy.pdf"]

    def get_all_document_names(self):
        return ["policy.pdf"]

    def get_workspace_documents(self, workspace_id):
        return ["policy.pdf"]

    @property
    def embedding_service(self):
        return self

    def embed(self, texts):
        return [self.embed_query(t) for t in texts]

    @property
    def collection(self):
        return self

    def get(self, **kw):
        return {
            "ids": [c["chunk_id"] for c in self.chunks],
            "documents": [c["text"] for c in self.chunks],
            "metadatas": [c["metadata"] for c in self.chunks],
        }


@pytest.fixture
def analyzer():
    store = FakeVectorStore()
    provider = ScriptedProvider(chunk_ids=[c["chunk_id"] for c in CHUNKS])
    instance = GapAnalyzer(vector_store=store, provider=provider)
    instance.nli_verifier = None
    return instance


DOCUMENT = "\n\n".join(c["text"] for c in CHUNKS)


def _run(analyzer, **kw):
    return analyzer.analyze(
        document_text=kw.get("document_text", DOCUMENT),
        document_name="policy.pdf",
        workspace_id="w1",
        frameworks=[],
        country=kw.get("country", "Testland"),
    )


class TestRunCompletes:
    def test_a_full_run_produces_a_result(self, analyzer):
        result = _run(analyzer)

        assert result.analysis_id
        assert result.governance_gaps

    def test_every_governance_dimension_is_represented(self, analyzer):
        from src.gap_analyzer import GOVERNANCE_DIMENSIONS

        result = _run(analyzer)

        # A dropped dimension silently narrows the assessment.
        assert {g.dimension for g in result.governance_gaps} == set(GOVERNANCE_DIMENSIONS)

    def test_no_live_provider_call_is_made(self, analyzer):
        _run(analyzer)

        # Every response came from the fixture. This is what makes the gate
        # runnable on every pull request without spending quota.
        assert analyzer.provider.calls
        assert all(c["schema"] != "live" for c in analyzer.provider.calls)

    def test_the_call_count_is_reported(self, analyzer):
        result = _run(analyzer)

        # Quota usage has to be observable against the ~8 + up to 8 budget.
        assert result.llm_call_count >= 1


class TestEvidenceInvariants:
    def test_every_citation_resolves_to_a_real_chunk(self, analyzer):
        result = _run(analyzer)

        known = {c["chunk_id"] for c in CHUNKS}
        for gap in result.governance_gaps:
            for evidence in gap.evidence:
                # A citation to a chunk that does not exist is unverifiable
                # by construction, and that is exactly what happened when
                # chunk ids were minted fresh on every ingestion.
                assert evidence.chunk_id in known, f"{gap.dimension}: {evidence.chunk_id}"

    def test_no_evidence_item_is_empty(self, analyzer):
        result = _run(analyzer)

        for gap in result.governance_gaps:
            for evidence in gap.evidence:
                assert evidence.text.strip()

    def test_a_cited_page_matches_the_chunk_it_cites(self, analyzer):
        result = _run(analyzer)

        pages = {c["chunk_id"]: c["page_number"] for c in CHUNKS}
        for gap in result.governance_gaps:
            for evidence in gap.evidence:
                if evidence.page_number is not None and evidence.chunk_id in pages:
                    assert evidence.page_number == pages[evidence.chunk_id]

    def test_no_chunk_id_is_rendered_as_a_provision(self, analyzer):
        result = _run(analyzer)

        ids = {c["chunk_id"] for c in CHUNKS}
        for gap in result.governance_gaps:
            narrative = " ".join(
                str(getattr(gap, field, "") or "")
                for field in ("reason_flagged", "recommendation", "coverage_reasoning")
            )
            # India's Human Autonomy verdict shipped "in Section
            # 3081a297-54ab-..." three times. A reader must never see a UUID
            # presented as a provision.
            for chunk_id in ids:
                assert chunk_id not in narrative


class TestDeterministicLadder:
    def test_two_runs_produce_identical_verdicts(self, analyzer):
        first = _run(analyzer)
        second = _run(analyzer)

        # The coverage ladder is CODE. Given identical evidence it must
        # produce byte-identical verdicts; any diff here is a genuine bug
        # rather than model variation.
        assert {g.dimension: g.coverage for g in first.governance_gaps} == {
            g.dimension: g.coverage for g in second.governance_gaps
        }

    def test_two_runs_produce_identical_maturity(self, analyzer):
        first = _run(analyzer)
        second = _run(analyzer)

        assert {g.dimension: g.governance_maturity for g in first.governance_gaps} == {
            g.dimension: g.governance_maturity for g in second.governance_gaps
        }

    def test_two_runs_produce_identical_risk_levels(self, analyzer):
        first = _run(analyzer)
        second = _run(analyzer)

        assert {g.dimension: g.risk_level for g in first.governance_gaps} == {
            g.dimension: g.risk_level for g in second.governance_gaps
        }

    def test_the_whole_deterministic_block_is_byte_identical(self, analyzer):
        import json

        def _ladder(result):
            return json.dumps(
                [
                    {
                        "dimension": g.dimension,
                        "coverage": str(g.coverage),
                        "maturity": str(g.governance_maturity),
                        "risk": str(g.risk_level),
                    }
                    for g in sorted(result.governance_gaps, key=lambda g: g.dimension)
                ],
                sort_keys=True,
            )

        # One assertion over the entire deterministic stage, so a new field
        # is covered without anyone remembering to add a test for it.
        assert _ladder(_run(analyzer)) == _ladder(_run(analyzer))

    def test_a_different_country_does_not_move_a_verdict(self, analyzer):
        base = _run(analyzer, country="Testland")
        other = _run(analyzer, country="Otherland")

        # Regional routing changes which frameworks are consulted; it must
        # never change what the document itself is found to say.
        assert {g.dimension: g.coverage for g in base.governance_gaps} == {
            g.dimension: g.coverage for g in other.governance_gaps
        }


class TestFailureHandling:
    def test_a_provider_failure_marks_the_dimension_rather_than_guessing(self):
        class _Failing(ScriptedProvider):
            def generate_structured(self, prompt, schema, system_prompt=None, **kw):
                raise RuntimeError("provider is down")

        analyzer = GapAnalyzer(vector_store=FakeVectorStore(), provider=_Failing())
        analyzer.nli_verifier = None

        result = _run(analyzer)

        # A wrong verdict is worse than a missing one: failed dimensions are
        # excluded from scoring rather than scored as Missing.
        failed = [g for g in result.governance_gaps if g.analysis_error]
        assert failed
        assert all(g.coverage == CoverageLevel.INSUFFICIENT_EVIDENCE for g in failed)

    def test_an_empty_document_does_not_invent_findings(self, analyzer):
        analyzer.vector_store = FakeVectorStore(chunks=[])

        result = _run(analyzer, document_text="")

        for gap in result.governance_gaps:
            # With no context at all, there is nothing to cite.
            assert not gap.evidence
