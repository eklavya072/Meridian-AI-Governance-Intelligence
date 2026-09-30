"""Tracing: stage spans, their nesting, and the ids stamped on log lines."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src import tracing

_EXPORTER = InMemorySpanExporter()


def _install_provider() -> None:
    """One SDK provider for the test process; OpenTelemetry allows only one."""
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(_EXPORTER))


_install_provider()


@pytest.fixture
def spans():
    _EXPORTER.clear()
    yield _EXPORTER
    _EXPORTER.clear()


def _by_name(exporter):
    return {s.name: s for s in exporter.get_finished_spans()}


class TestStage:
    def test_nested_stages_share_one_trace(self, spans):
        with tracing.stage("analysis.run", workspace_id="w1"):
            with tracing.stage("analyse"):
                pass
        got = _by_name(spans)
        root, child = got["analysis.run"], got["analyse"]
        assert child.parent.span_id == root.context.span_id
        assert child.context.trace_id == root.context.trace_id
        assert root.attributes["workspace_id"] == "w1"

    def test_none_attributes_are_dropped(self, spans):
        with tracing.stage("index", chunks=None, document="policy.pdf"):
            pass
        attrs = _by_name(spans)["index"].attributes
        assert "chunks" not in attrs
        assert attrs["document"] == "policy.pdf"

    def test_a_failing_stage_still_ends_its_span(self, spans):
        with pytest.raises(RuntimeError), tracing.stage("verify"):
            raise RuntimeError("boom")
        assert "verify" in _by_name(spans)


class TestTraced:
    def test_records_the_named_keyword_arguments(self, spans):
        @tracing.traced("llm", "operation")
        def call(prompt, operation="unknown"):
            return prompt.upper()

        assert call("hi", operation="module1_2_privacy") == "HI"
        span = _by_name(spans)["llm"]
        assert span.attributes["operation"] == "module1_2_privacy"

    def test_keeps_the_wrapped_name(self):
        @tracing.traced("retrieve", "dimension")
        def retrieve_module_chunks(dimension=""):
            return dimension

        assert retrieve_module_chunks.__name__ == "retrieve_module_chunks"


class TestInContext:
    def test_pool_work_is_parented_to_the_submitting_span(self, spans):
        def work(i):
            with tracing.stage("llm", operation=f"op{i}"):
                return i

        with tracing.stage("analyse"), ThreadPoolExecutor(max_workers=3) as pool:
            bound = [tracing.in_context(work) for _ in range(4)]
            assert list(pool.map(lambda run, i: run(i), bound, range(4))) == [0, 1, 2, 3]

        finished = spans.get_finished_spans()
        parent = next(s for s in finished if s.name == "analyse")
        children = [s for s in finished if s.name == "llm"]
        assert len(children) == 4
        assert all(s.parent.span_id == parent.context.span_id for s in children)

    def test_without_it_pool_work_starts_a_new_trace(self, spans):
        def work():
            with tracing.stage("llm"):
                pass

        with tracing.stage("analyse"), ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(work).result()
        orphan = _by_name(spans)["llm"]
        assert orphan.parent is None


class TestLogCorrelation:
    def test_ids_are_added_inside_a_span(self, spans):
        with tracing.stage("analyse") as span:
            event = tracing.add_trace_ids(None, "info", {"event": "x"})
        ctx = span.get_span_context()
        assert event["trace_id"] == format(ctx.trace_id, "032x")
        assert event["span_id"] == format(ctx.span_id, "016x")

    def test_nothing_is_added_outside_a_span(self):
        assert tracing.add_trace_ids(None, "info", {"event": "x"}) == {"event": "x"}


class TestSetup:
    def test_no_exporter_leaves_tracing_off(self, monkeypatch):
        monkeypatch.delenv("OTEL_TRACES_EXPORTER", raising=False)
        before = trace.get_tracer_provider()
        tracing.setup_tracing()
        assert trace.get_tracer_provider() is before

    def test_an_unknown_exporter_is_ignored(self, monkeypatch):
        monkeypatch.setenv("OTEL_TRACES_EXPORTER", "zipkin-please")
        before = trace.get_tracer_provider()
        tracing.setup_tracing()
        assert trace.get_tracer_provider() is before


def test_a_replayed_analysis_is_one_trace(spans):
    """The whole run, dimension workers included, hangs off one root span."""
    from src.gap_analyzer import GapAnalyzer
    from tests.unit.test_pipeline_replay import CHUNKS, FakeVectorStore, ScriptedProvider

    analyzer = GapAnalyzer(
        vector_store=FakeVectorStore(),
        provider=ScriptedProvider(chunk_ids=[c["chunk_id"] for c in CHUNKS]),
    )
    with tracing.stage("analysis.run", workspace_id="w1") as root:
        analyzer.analyze(
            document_text="\n\n".join(c["text"] for c in CHUNKS),
            document_name="policy.pdf",
            workspace_id="w1",
            frameworks=[],
            country="Testland",
        )
    finished = spans.get_finished_spans()
    trace_id = root.get_span_context().trace_id
    llm = [s for s in finished if s.name == "llm"]
    retrieve = [s for s in finished if s.name == "retrieve"]
    assert llm and retrieve
    assert all(s.context.trace_id == trace_id for s in finished)
    assert all(s.attributes.get("operation") for s in llm)
