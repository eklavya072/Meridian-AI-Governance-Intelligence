"""Shared test fixtures.

Two things live here: a sandbox for every on-disk state file (below), and
process-global state reset, which exists because of a
real order-dependent failure: `provider_router` memoises its provider client
in a module global the first time one is constructed successfully. A test that
sets an API key through monkeypatch gets the environment restored afterwards —
but monkeypatch cannot reach inside the module and drop the client that was
already built, so every later test in the same process saw a live provider and
`test_every_credential_exhausted_raises_a_clear_error` stopped raising.

That surfaced as a test that passed alone and failed in the suite, which is
the most expensive kind of failure to chase. Resetting the globals between
tests makes the suite order-independent.
"""

import os
import tempfile

import pytest

# Every path the app writes live state to, pointed at a throwaway directory
# BEFORE any `src` module is imported (they read these into module constants
# at import time). Without it the unit suite opened the real
# backend/data/chroma — the scoring tests reach framework_salience, which
# builds a default VectorStore — so running the suite beside a live API was
# two processes on one embedded Chroma directory, the one thing that corrupts
# it. The retrieval-quality evaluation needs the real index and is opt-in, so
# it keeps the real paths.
if not os.getenv("RUN_EVALUATION_TESTS"):
    _SANDBOX = tempfile.mkdtemp(prefix="meridian-tests-")
    os.environ["CHROMA_PERSIST_DIR"] = os.path.join(_SANDBOX, "chroma")
    os.environ["UPLOAD_DIR"] = os.path.join(_SANDBOX, "uploads")
    os.environ["PROVIDER_HEALTH_FILE"] = os.path.join(_SANDBOX, "provider_health.json")
    os.environ["GEMINI_RPD_FILE"] = os.path.join(_SANDBOX, "gemini_rpd.json")


@pytest.fixture(autouse=True)
def _reset_provider_router_globals():
    """Drop cached provider clients around every test."""
    try:
        from src import provider_router as pr
    except Exception:  # provider_router unimportable in a stripped environment
        yield
        return

    names = ("_provider",)
    saved = {n: getattr(pr, n, None) for n in names}
    for n in names:
        if hasattr(pr, n):
            setattr(pr, n, None)
    try:
        yield
    finally:
        for n, v in saved.items():
            if hasattr(pr, n):
                setattr(pr, n, v)
