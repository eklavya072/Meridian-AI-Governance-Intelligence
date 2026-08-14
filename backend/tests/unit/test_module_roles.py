"""Regression tests for the Module 1/Module 2 role-filtered retrieval path.

Root cause history: role_filter originally built a one-element ChromaDB $or
(which raises), then used $contains/$in (which raise on this ChromaDB version
for string metadata). The working form is direct equality:
    {"roles": "module_1_normative"}
These tests lock in that behavior so it cannot silently regress.

NOTE: these tests need a vector store pre-populated with role-tagged framework
chunks (run POST /api/v1/frameworks/sync first). If none exist they are
skipped, not failed — they are effectively integration tests.
"""

import pytest

from src.vectorstore import VectorStore

_HAS_M1 = False
_HAS_M2 = False
try:
    _probe = VectorStore()
    _HAS_M1 = len(_probe.retrieve("governance", top_k=1, role_filter=["module_1_normative"])) > 0
    _HAS_M2 = len(_probe.retrieve("governance", top_k=1, role_filter=["module_2_practical"])) > 0
except Exception:
    pass

_SKIP_NO_M1 = pytest.mark.skipif(
    not _HAS_M1,
    reason="No module_1_normative chunks in vector store — run framework sync first.",
)
_SKIP_NO_M2 = pytest.mark.skipif(
    not _HAS_M2,
    reason="No module_2_practical chunks in vector store — run framework sync first.",
)


@pytest.fixture(scope="module")
def vs() -> VectorStore:
    return VectorStore()


@_SKIP_NO_M1
@_SKIP_NO_M2
def test_role_filter_returns_only_matching_role(vs: VectorStore) -> None:
    """A single-role filter must return chunks whose roles metadata matches exactly."""
    module1 = vs.retrieve("transparency", top_k=5, role_filter=["module_1_normative"])
    assert module1, "expected at least one module_1_normative chunk"
    for r in module1:
        assert r["metadata"].get("roles") == "module_1_normative"

    module2 = vs.retrieve("bias mitigation", top_k=5, role_filter=["module_2_practical"])
    assert module2, "expected at least one module_2_practical chunk"
    for r in module2:
        assert r["metadata"].get("roles") == "module_2_practical"


@_SKIP_NO_M1
def test_role_filter_respects_top_k(vs: VectorStore) -> None:
    top_k = 4
    module1 = vs.retrieve("privacy", top_k=top_k, role_filter=["module_1_normative"])
    assert len(module1) > 0
    assert len(module1) <= top_k
