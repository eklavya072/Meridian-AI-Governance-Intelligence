"""Record real Gemini answers for the replay gate (tests/recorded_provider.py).

Runs the replay gate's own analysis once against the live model and writes
every structured answer, keyed by request hash, to
tests/fixtures/replay/gemini-recording.json. About ten requests: one
mechanism check, one evaluation per dimension, one roadmap call.

Re-run only when a prompt changes (the gate then fails with a missing-hash
error). Uses GEMINI_API_KEY alone and the default batching, so the recorded
requests are exactly the ones the gate will make.

    cd backend && uv run python scripts/record_replay_fixtures.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env")
# One key, default pipeline settings: the requests must match the gate's.
for name in list(os.environ):
    if name.startswith("GEMINI_API_KEY_") or name in (
        "BATCH_LLM_CALLS",
        "BATCH_EVALUATION",
        "MECHANISM_ADJUDICATION",
        "MERIDIAN_REPLAY",
        "LLM_PROVIDER",
    ):
        del os.environ[name]
if not os.getenv("GEMINI_API_KEY"):
    sys.exit("GEMINI_API_KEY is not set.")

from src.gap_analyzer import GapAnalyzer  # noqa: E402
from src.llm_provider import GeminiProvider  # noqa: E402
from tests.recorded_provider import FIXTURE_DIR, FIXTURE_FILE, request_key, scrub  # noqa: E402
from tests.unit.test_pipeline_replay import FakeVectorStore, _run  # noqa: E402


def main() -> None:
    answers: dict[str, dict] = {}
    live = GeminiProvider.generate_structured

    def recording(self, prompt, schema, system_prompt=None, **kw):
        result = live(self, prompt, schema, system_prompt=system_prompt, **kw)
        answers[request_key(schema.__name__, system_prompt, prompt)] = {
            "schema": schema.__name__,
            "answer": scrub(result.model_dump(mode="json")),
        }
        return result

    GeminiProvider.generate_structured = recording  # type: ignore[method-assign]
    provider = GeminiProvider()
    result = _run(GapAnalyzer(vector_store=FakeVectorStore(), provider=provider))

    failed = [g.dimension for g in result.governance_gaps if g.analysis_error]
    if failed:
        sys.exit(f"Not written: the live run failed on {failed}. Nothing to record.")

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURE_FILE.write_text(
        json.dumps(
            {
                "model": provider.model_name,
                "recorded": datetime.now(UTC).date().isoformat(),
                "requests": len(answers),
                "answers": dict(sorted(answers.items())),
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{len(answers)} answers from {provider.model_name} -> {FIXTURE_FILE}")


if __name__ == "__main__":
    main()
