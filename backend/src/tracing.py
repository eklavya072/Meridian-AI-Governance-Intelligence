"""OpenTelemetry tracing: one span per pipeline stage.

Off unless OTEL_TRACES_EXPORTER is set, and a no-op tracer costs nothing:

    OTEL_TRACES_EXPORTER=otlp     OTLP over HTTP to OTEL_EXPORTER_OTLP_ENDPOINT
                                  (Jaeger, Tempo, or a collector)
    OTEL_TRACES_EXPORTER=console  one JSON span per line on stdout

A run is traced as `analysis.run`, with `ingest`, `index` and `analyse` under
it; `analyse` holds `retrieve` and one `llm` span per model call, and
`verify` follows. Briefs add `synthesise` and `export`, uploads `validate`.
Every stage also feeds the stage-latency histogram, so a trace and the
Prometheus dashboard use the same stage names.

Log lines emitted inside a span carry its trace_id, so one analysis can be
followed from the logs to the trace and back.
"""

from __future__ import annotations

import contextvars
import functools
import os
from collections.abc import Callable, Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any

import structlog
from opentelemetry import trace

from src import metrics

logger = structlog.get_logger()

_tracer = trace.get_tracer("meridian")


def setup_tracing() -> None:
    """Install the exporter named by OTEL_TRACES_EXPORTER, if any."""
    kind = os.getenv("OTEL_TRACES_EXPORTER", "none").strip().lower()
    if kind in ("", "none"):
        return
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    exporter: Any
    if kind == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter()
    elif kind == "console":
        exporter = ConsoleSpanExporter(formatter=lambda span: span.to_json(indent=None) + "\n")
    else:
        logger.warning("unknown_traces_exporter", exporter=kind)
        return
    provider = TracerProvider(
        resource=Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "meridian-api")})
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info("tracing_enabled", exporter=kind)


@contextmanager
def stage(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """A span for one pipeline stage, also timed in the stage histogram."""
    attrs = {k: v for k, v in attributes.items() if v is not None}
    with (
        _tracer.start_as_current_span(name, attributes=attrs) as span,
        metrics.timed_stage(name),
    ):
        yield span


def traced(name: str, *kwarg_attributes: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator form of `stage`, recording the named keyword arguments."""

    def decorate[T](fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            attrs = {k: kwargs.get(k) for k in kwarg_attributes}
            with stage(name, **attrs):
                return fn(*args, **kwargs)

        return wrapper

    return decorate


def in_context[T](fn: Callable[..., T]) -> Callable[..., T]:
    """Bind `fn` to the caller's context, for work handed to a thread pool.

    A pool thread starts with an empty context, so without this a span opened
    there has no parent and a log line loses the run it belongs to. One copy
    per call: a context cannot be entered by two threads at once.
    """
    ctx = contextvars.copy_context()
    return lambda *args, **kwargs: ctx.run(fn, *args, **kwargs)


def add_trace_ids(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: stamp the current trace and span ids on a log line."""
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict
