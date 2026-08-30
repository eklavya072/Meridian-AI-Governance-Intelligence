"""Replay mode: run the whole pipeline with no provider behind it.

Two things need this and neither can use the live API.

Load testing, because pointing k6 at a paid, rate-limited endpoint measures
the provider's queue rather than Meridian's pipeline — and burns quota to do
it. Replay isolates our own cost, which is the more useful engineering
number.

And the evidence gate, which has to run on every pull request. A gate that
needs credentials is a gate that gets skipped.

Responses are generated from the request's own schema rather than replayed
from captured traffic. That is a deliberate trade: recorded fixtures would
be more faithful, but they would also mean real model output — and real
document text — living in the repository, with a scrubbing step that has to
be right every time. Schema-shaped responses cannot leak anything because
nothing real ever enters them.

Enabled with MERIDIAN_REPLAY=1. Off by default, and provenance records
which mode produced every brief, so a replay run can never be mistaken for
a live one.
"""

from __future__ import annotations

import hashlib
import os
import time
from enum import Enum
from typing import Any, get_args, get_origin

import structlog
from pydantic import BaseModel

from src.llm_provider import LLMProvider

logger = structlog.get_logger()

# A fixed, small delay per call so a load test measures something realistic
# rather than an instant return. Zero would make the pipeline look free and
# produce latency numbers that flatter it beyond usefulness.
REPLAY_LATENCY_SECONDS = float(os.getenv("MERIDIAN_REPLAY_LATENCY", "0.05"))


def is_replay_enabled() -> bool:
    return os.getenv("MERIDIAN_REPLAY", "").strip().lower() in ("1", "true", "yes")


def _deterministic_text(prompt: str, field: str) -> str:
    """Stable filler derived from the request, so a replay run is reproducible.

    Keyed on the prompt so the same request always produces the same
    response — which is what lets the coverage ladder be asserted
    byte-identical across runs.
    """
    digest = hashlib.sha1(f"{prompt}|{field}".encode()).hexdigest()[:8]
    return f"Replay fixture {field} ({digest})."


def _fill(schema: type[BaseModel], prompt: str, chunk_ids: list[str]) -> BaseModel:
    values: dict[str, Any] = {}
    for name, model_field in schema.model_fields.items():
        if not model_field.is_required():
            continue
        values[name] = _value_for(model_field.annotation, name, prompt, chunk_ids)
    return schema(**values)


def _value_for(annotation: Any, name: str, prompt: str, chunk_ids: list[str]) -> Any:
    origin = get_origin(annotation)
    if origin in (list, set, tuple):
        return []
    if origin is dict:
        return {}
    if origin is not None and type(None) in get_args(annotation):
        return None
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return list(annotation)[0]
    if annotation is bool:
        return False
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is str:
        # Citations must point at chunks that actually exist, or the evidence
        # gate's own invariant fails against its own fixtures.
        if "chunk_id" in name and chunk_ids:
            return chunk_ids[0]
        return _deterministic_text(prompt, name)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _fill(annotation, prompt, chunk_ids)
    return None


class ReplayProvider(LLMProvider):
    """A provider that answers from the request's schema, never the network."""

    def __init__(self) -> None:
        self.model_name_str = "replay-fixture"
        self.call_count = 0
        logger.warning(
            "replay_mode_enabled",
            detail="No provider calls will be made. Output is fixture data.",
        )

    @property
    def tier(self) -> str:
        # NOT "primary": that is what makes generate_with_retry skip the
        # quota checks, the throttles and the key rotation entirely, which is
        # exactly what a replay run wants.
        return "replay"

    @property
    def model_name(self) -> str:
        return self.model_name_str

    def _chunk_ids_in(self, prompt: str) -> list[str]:
        """Chunk ids the prompt actually showed the model.

        A fixture citing an id that was never in context would fail the
        evidence gate for the wrong reason — the pipeline would be fine and
        the fixture would be lying.
        """
        import re

        return re.findall(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", prompt
        )

    def generate_structured(
        self, prompt: str, schema: type, system_prompt: str | None = None, **kw
    ):
        self.call_count += 1
        if REPLAY_LATENCY_SECONDS > 0:
            time.sleep(REPLAY_LATENCY_SECONDS)
        return _fill(schema, prompt, self._chunk_ids_in(prompt))

    def generate_text(self, prompt: str, system_prompt: str | None = None, **kw) -> str:
        self.call_count += 1
        if REPLAY_LATENCY_SECONDS > 0:
            time.sleep(REPLAY_LATENCY_SECONDS)
        return _deterministic_text(prompt, "reply")
