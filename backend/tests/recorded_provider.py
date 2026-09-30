"""Real Gemini answers, recorded once and replayed by request hash.

scripts/record_replay_fixtures.py runs the replay gate's own analysis once
against the live model and stores every structured answer, keyed by a hash of
the request that produced it (schema name, system prompt, prompt). The gate
then replays those answers with no network and no quota, so its invariants
are checked against what the model actually returns — including its mistakes
— rather than against a scripted, well-behaved fake.

A request with no recording fails loudly: a prompt edit changes the hash, and
the fix is to re-record, not to fall back to something that always passes.

What is stored is the model's structured output only. The prompts are built
from the test's own synthetic two-article policy, so no document, key or
personal data is captured; scrub() is still applied before anything is
written, and the file is checked for key-shaped strings by the tests.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "replay"
FIXTURE_FILE = FIXTURE_DIR / "gemini-recording.json"

# Credential and contact shapes that must never reach a committed fixture.
SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),  # Google API key
    re.compile(r"hf_[A-Za-z0-9]{30,}"),  # Hugging Face token
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # e-mail address
)


def request_key(schema_name: str, system_prompt: str | None, prompt: str) -> str:
    payload = json.dumps([schema_name, system_prompt or "", prompt], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def scrub(value: Any) -> Any:
    """Replace anything credential- or address-shaped, recursively."""
    if isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            value = pattern.sub("[scrubbed]", value)
        return value
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    return value


def load_recording() -> dict[str, Any] | None:
    if not FIXTURE_FILE.exists():
        return None
    return json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))


class MissingRecording(KeyError):
    pass


class RecordedProvider:
    """Serves recorded answers; raises on any request it has not seen."""

    tier = "primary"

    def __init__(self, recording: dict[str, Any]):
        self.model_name = recording["model"]
        self._answers = recording["answers"]
        self.calls: list[dict[str, str]] = []

    def generate_structured(self, prompt, schema, system_prompt=None, **kw):
        key = request_key(schema.__name__, system_prompt, prompt)
        if key not in self._answers:
            raise MissingRecording(
                f"No recorded answer for this {schema.__name__} request; the prompt "
                "changed since recording. Re-record: "
                "uv run python scripts/record_replay_fixtures.py"
            )
        self.calls.append({"schema": schema.__name__, "key": key})
        return schema.model_validate(self._answers[key]["answer"])

    def generate_text(self, prompt, system_prompt=None, **kw):
        raise MissingRecording("The analysis path makes no free-text calls.")
