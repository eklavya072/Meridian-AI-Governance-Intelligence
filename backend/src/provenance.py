"""What produced this brief, recorded with it.

When an auditor asks "how was this conclusion produced, and does it
reproduce", there has to be an answer that does not depend on someone
remembering which build was deployed in August. A verdict is only defensible
if the machinery behind it is identifiable.

Every field is DERIVED, never hand-typed. A hand-maintained version string
is wrong the first time a threshold moves, and a provenance record that
drifts is worse than none because it is believed.

The framework corpus hash deserves a note: it is over the routing config
(name, version, checksum per framework), not the vector store. The store
also holds every uploaded country document, so hashing it would make the
corpus fingerprint change whenever an unrelated workspace uploaded a file —
which would make the hash useless for the question it exists to answer.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import structlog

logger = structlog.get_logger()

# Bumped by hand when the prompt text changes in a way that could move a
# verdict. It is the one value that cannot be derived, because "the prompts
# changed meaningfully" is a judgment rather than a fact about the bytes.
PROMPT_VERSION = "2026.08.1"


@lru_cache(maxsize=1)
def _git_revision() -> str:
    """The commit that built this, when git is available.

    The container has no .git, so this normally comes from GIT_SHA, injected
    at build time. Falling back to "unknown" is correct: claiming a revision
    we cannot verify would defeat the point.
    """
    env = os.getenv("GIT_SHA", "").strip()
    if env:
        return env[:40]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip()[:40]
    except Exception:
        pass
    return "unknown"


@lru_cache(maxsize=1)
def framework_corpus_hash() -> str:
    """Fingerprint of the framework corpus this analysis was scored against.

    Two runs that disagree while carrying the same hash are a code
    difference; two that disagree with different hashes may simply have been
    scored against different reference material.
    """
    try:
        from src.framework_sync import load_frameworks_config

        entries = sorted(
            (
                str(fw.get("name", "")),
                str(fw.get("version", "")),
                str(fw.get("checksum", "")),
            )
            for fw in load_frameworks_config()
        )
    except Exception as exc:
        logger.warning("framework_corpus_hash_failed", error=str(exc))
        return "unknown"

    digest = hashlib.sha256()
    for name, version, checksum in entries:
        digest.update(f"{name}|{version}|{checksum}\n".encode())
    return f"sha256:{digest.hexdigest()[:16]} ({len(entries)} frameworks)"


def is_replay_mode() -> bool:
    """True when responses came from committed fixtures, not the provider."""
    return os.getenv("MERIDIAN_REPLAY", "").strip().lower() in ("1", "true", "yes")


def build_provenance(
    llm_model: str | None = None,
    llm_calls: int | None = None,
) -> dict[str, Any]:
    """The provenance record persisted with an analysis and rendered in exports."""
    from src.nli_verifier import ENABLE_NLI_VERIFICATION, NLI_MODEL
    from src.vectorstore import EMBEDDING_MODEL_NAME
    from src.verify import SEMANTIC_THRESHOLD, SEMANTIC_VERIFICATION

    # Name the check that actually ran. The README claimed NLI for months
    # while the flag defaulted to off and embedding similarity did the work;
    # a provenance record that repeats that claim would launder it.
    if ENABLE_NLI_VERIFICATION:
        verification = {"method": "nli_cross_encoder", "model": NLI_MODEL}
    elif SEMANTIC_VERIFICATION:
        verification = {
            "method": "embedding_similarity",
            "model": EMBEDDING_MODEL_NAME,
            "threshold": SEMANTIC_THRESHOLD,
        }
    else:
        verification = {"method": "disabled"}

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "meridian_revision": _git_revision(),
        "embedding_model": EMBEDDING_MODEL_NAME,
        "verification": verification,
        "llm_model": llm_model or os.getenv("GEMINI_MODEL", "unknown"),
        "llm_calls": llm_calls,
        "prompt_version": PROMPT_VERSION,
        "framework_corpus": framework_corpus_hash(),
        "mode": "replay" if is_replay_mode() else "live",
    }


def render_provenance_lines(provenance: dict[str, Any]) -> list[str]:
    """Flat, human-readable lines for the PDF and DOCX footers."""
    if not provenance:
        return []
    verification = provenance.get("verification") or {}
    method = verification.get("method", "unknown")
    if verification.get("model"):
        method = f"{method} ({verification['model']})"
    lines = [
        f"Generated: {provenance.get('generated_at', 'unknown')}",
        f"Mode: {provenance.get('mode', 'unknown')}",
        f"Language model: {provenance.get('llm_model', 'unknown')}",
        f"Prompt version: {provenance.get('prompt_version', 'unknown')}",
        f"Embedding model: {provenance.get('embedding_model', 'unknown')}",
        f"Citation verification: {method}",
        f"Framework corpus: {provenance.get('framework_corpus', 'unknown')}",
        f"Build: {provenance.get('meridian_revision', 'unknown')}",
    ]
    if provenance.get("llm_calls") is not None:
        lines.insert(3, f"Language-model calls: {provenance['llm_calls']}")
    return lines
