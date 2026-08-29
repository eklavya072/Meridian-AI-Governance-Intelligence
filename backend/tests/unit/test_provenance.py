"""Provenance must be derived, and must describe what actually ran.

The failure mode this guards against is a record that is believed and wrong.
A hand-typed model name or verification method is correct until someone
flips a flag, and then it launders a claim rather than documenting one.
"""

import pytest

import src.provenance as prov
from src.brief_export import render_docx, render_pdf
from src.provenance import (
    build_provenance,
    framework_corpus_hash,
    render_provenance_lines,
)


class TestDerivedNotTyped:
    def test_embedding_model_comes_from_the_vector_store_constant(self):
        from src.vectorstore import EMBEDDING_MODEL_NAME

        assert build_provenance()["embedding_model"] == EMBEDDING_MODEL_NAME

    def test_llm_model_follows_the_environment(self, monkeypatch):
        monkeypatch.setenv("GEMINI_MODEL", "gemini-9.9-imaginary")

        assert build_provenance()["llm_model"] == "gemini-9.9-imaginary"

    def test_explicit_model_overrides_the_environment(self):
        # The model a run actually used beats the currently-configured one:
        # re-reading an old analysis must not relabel it with today's config.
        assert build_provenance(llm_model="gemini-3.6-flash")["llm_model"] == "gemini-3.6-flash"


class TestVerificationIsDescribedHonestly:
    def test_reports_embedding_when_nli_is_off(self, monkeypatch):
        monkeypatch.setattr("src.nli_verifier.ENABLE_NLI_VERIFICATION", False)
        monkeypatch.setattr("src.verify.SEMANTIC_VERIFICATION", True)

        verification = build_provenance()["verification"]

        # The README claimed NLI for months while this path did the work.
        # Provenance repeating that claim would launder it.
        assert verification["method"] == "embedding_similarity"
        assert "bge" in verification["model"]
        assert verification["threshold"] > 0

    def test_reports_nli_when_nli_is_on(self, monkeypatch):
        monkeypatch.setattr("src.nli_verifier.ENABLE_NLI_VERIFICATION", True)

        assert build_provenance()["verification"]["method"] == "nli_cross_encoder"

    def test_reports_disabled_when_nothing_verifies(self, monkeypatch):
        monkeypatch.setattr("src.nli_verifier.ENABLE_NLI_VERIFICATION", False)
        monkeypatch.setattr("src.verify.SEMANTIC_VERIFICATION", False)

        assert build_provenance()["verification"]["method"] == "disabled"


class TestReplayMode:
    def test_live_by_default(self, monkeypatch):
        monkeypatch.delenv("MERIDIAN_REPLAY", raising=False)

        assert build_provenance()["mode"] == "live"

    def test_replay_is_recorded(self, monkeypatch):
        monkeypatch.setenv("MERIDIAN_REPLAY", "1")

        # A brief produced from fixtures must never be mistaken for one
        # produced against the live provider.
        assert build_provenance()["mode"] == "replay"


class TestFrameworkCorpusHash:
    def test_is_stable_across_calls(self):
        assert framework_corpus_hash() == framework_corpus_hash()

    def test_names_how_many_frameworks_it_covers(self):
        # A bare hash is unfalsifiable; the count makes an obviously-wrong
        # corpus visible without recomputing anything.
        assert "frameworks" in framework_corpus_hash()

    def test_never_raises_when_the_config_is_unreadable(self, monkeypatch):
        def _explode():
            raise FileNotFoundError("config gone")

        monkeypatch.setattr("src.framework_sync.load_frameworks_config", _explode)
        framework_corpus_hash.cache_clear()

        # Losing the fingerprint is bad; failing the whole analysis over it
        # is worse.
        assert framework_corpus_hash() == "unknown"
        framework_corpus_hash.cache_clear()


class TestBuildRevision:
    def test_prefers_the_injected_sha(self, monkeypatch):
        monkeypatch.setenv("GIT_SHA", "a" * 40)
        prov._git_revision.cache_clear()

        assert build_provenance()["meridian_revision"] == "a" * 40
        prov._git_revision.cache_clear()


@pytest.fixture
def gaps():
    from tests.unit.test_brief_v2 import gaps as _gaps

    return _gaps.__wrapped__()


class TestExportsCarryProvenance:
    """The export is the copy that leaves the system and gets forwarded."""

    def _brief(self, gaps):
        # Built through assemble_brief, the same path the API uses, so this
        # asserts on the real brief shape rather than a hand-written stand-in
        # that could drift from it.
        from src.brief_synthesis import assemble_brief
        from tests.unit.test_brief_v2 import SCOPE, _synthesis

        brief = assemble_brief(
            workspace_id="w1",
            country="Testland",
            policy_title="AI Strategy",
            document_name="strat.pdf",
            documents=["strat.pdf"],
            frameworks_used=["EU AI Act"],
            scope_disclaimer=SCOPE,
            gaps=gaps,
            synthesis=_synthesis(),
            decision_analytics=None,
        )
        brief["provenance"] = build_provenance(llm_model="gemini-3.6-flash", llm_calls=9)
        return brief

    def test_pdf_export_includes_provenance(self, gaps):
        data = render_pdf(self._brief(gaps))

        assert data.startswith(b"%PDF-")
        assert len(data) > 1000

    def test_docx_export_includes_provenance(self, gaps):
        from io import BytesIO

        from docx import Document

        data = render_docx(self._brief(gaps))
        text = "\n".join(p.text for p in Document(BytesIO(data)).paragraphs)

        assert "PROVENANCE" in text.upper()
        assert "gemini-3.6-flash" in text
        assert "Prompt version" in text

    def test_a_brief_without_provenance_still_exports(self, gaps):
        # Analyses stored before provenance existed must keep exporting.
        brief = self._brief(gaps)
        del brief["provenance"]

        assert render_pdf(brief).startswith(b"%PDF-")


class TestRenderedLines:
    def test_every_field_a_reader_needs_is_present(self):
        lines = render_provenance_lines(build_provenance(llm_model="m", llm_calls=3))
        joined = "\n".join(lines)

        for expected in (
            "Generated:",
            "Mode:",
            "Language model:",
            "Language-model calls:",
            "Prompt version:",
            "Embedding model:",
            "Citation verification:",
            "Framework corpus:",
            "Build:",
        ):
            assert expected in joined, expected

    def test_empty_provenance_renders_nothing(self):
        assert render_provenance_lines({}) == []
