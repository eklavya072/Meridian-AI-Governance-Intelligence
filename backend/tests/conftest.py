"""Shared test fixtures.

The only thing here is process-global state reset, and it exists because of a
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

import pytest


@pytest.fixture(autouse=True)
def _reset_provider_router_globals():
    """Drop cached provider clients around every test."""
    try:
        from src import provider_router as pr
    except Exception:  # provider_router unimportable in a stripped environment
        yield
        return

    names = ("_provider", "_original_provider")
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
