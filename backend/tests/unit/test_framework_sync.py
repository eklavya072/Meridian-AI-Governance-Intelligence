"""Framework sync: every branch, with a fake index and no network."""

import hashlib
from pathlib import Path

import pytest

from src import framework_sync as fs
from src.ingestion import Chunk

PDF_BYTES = b"%PDF-1.4 fake framework body"


class FakeIndex:
    def __init__(self, indexed=0, fail_add=False):
        self.indexed = indexed
        self.fail_add = fail_add
        self.events = []
        self.added = []

    def count_chunks(self, framework_filter=None):
        return self.indexed

    def delete_framework_chunks(self, name):
        self.events.append(("delete", name))

    def add_chunks(self, chunks):
        if self.fail_add:
            raise RuntimeError("index unavailable")
        self.events.append(("add", len(chunks)))
        self.added = list(chunks)
        return len(chunks)


def _chunks(n=2):
    return [
        Chunk(chunk_id=f"base-{i}", text=f"provision {i}", metadata={"roles": "module_1_normative"})
        for i in range(n)
    ]


@pytest.fixture
def raw_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fs, "RAW_POLICIES_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def ingest(monkeypatch):
    calls = []

    def fake(file_path, framework_name=None, roles=None, source_type=None, **kw):
        calls.append({"path": Path(file_path), "name": framework_name, "roles": roles})
        return _chunks()

    monkeypatch.setattr(fs, "ingest_document", fake)
    return calls


def _local(raw_dir, name="OECD Principles"):
    path = raw_dir / f"{name.replace(' ', '_')}.pdf"
    path.write_bytes(PDF_BYTES)
    return path


class TestWithoutALocalCopy:
    def test_an_indexed_framework_is_left_alone(self, raw_dir, ingest):
        index = FakeIndex(indexed=40)
        result = fs.FrameworkSyncService(index).sync_framework(
            {"name": "OECD Principles", "pdf_url": "https://example.org/oecd.pdf"}
        )
        assert result["status"] == "synced"
        assert result["chunk_count"] == 40
        assert not ingest and not index.events

    def test_no_url_is_an_error(self, raw_dir, ingest):
        result = fs.FrameworkSyncService(FakeIndex()).sync_framework({"name": "OECD Principles"})
        assert result["status"] == "error"
        assert "No PDF URL" in result["error"]

    def test_a_failed_download_is_an_error(self, raw_dir, ingest, monkeypatch):
        def boom(*a, **kw):
            raise ConnectionError("unreachable")

        monkeypatch.setattr(fs.httpx, "get", boom)
        result = fs.FrameworkSyncService(FakeIndex()).sync_framework(
            {"name": "OECD Principles", "pdf_url": "https://example.org/oecd.pdf"}
        )
        assert result["status"] == "error"
        assert "Download failed" in result["error"]

    def test_a_downloaded_page_that_is_not_a_pdf_is_refused(self, raw_dir, ingest, monkeypatch):
        class Page:
            headers = {"content-type": "text/html"}
            content = b"<html>blocked</html>"

            def raise_for_status(self):
                pass

        monkeypatch.setattr(fs.httpx, "get", lambda *a, **kw: Page())
        result = fs.FrameworkSyncService(FakeIndex()).sync_framework(
            {"name": "OECD Principles", "pdf_url": "https://example.org/oecd.pdf"}
        )
        assert result["status"] == "error"
        assert "not a PDF" in result["error"]
        assert not ingest

    def test_a_downloaded_pdf_is_saved_ingested_and_indexed(self, raw_dir, ingest, monkeypatch):
        class Pdf:
            headers = {"content-type": "application/pdf"}
            content = PDF_BYTES

            def raise_for_status(self):
                pass

        monkeypatch.setattr(fs.httpx, "get", lambda *a, **kw: Pdf())
        index = FakeIndex()
        result = fs.FrameworkSyncService(index).sync_framework(
            {"name": "OECD Principles", "pdf_url": "https://example.org/oecd.pdf"}
        )
        saved = raw_dir / "OECD_Principles.pdf"
        assert saved.read_bytes() == PDF_BYTES
        assert result == {
            "name": "OECD Principles",
            "version": "",
            "status": "synced",
            "checksum": hashlib.sha256(PDF_BYTES).hexdigest(),
            "chunk_count": 2,
        }
        assert ingest[0]["path"] == saved
        assert index.events == [("add", 2)]


class TestWithALocalCopy:
    def test_an_unchanged_indexed_file_is_skipped(self, raw_dir, ingest):
        path = _local(raw_dir)
        checksum = fs.compute_file_hash(path)
        index = FakeIndex(indexed=12)
        result = fs.FrameworkSyncService(index).sync_framework(
            {"name": "OECD Principles", "checksum": checksum}
        )
        assert result["status"] == "synced"
        assert result["chunk_count"] == 12
        assert not ingest and not index.events

    def test_a_changed_file_is_ingested_before_the_old_chunks_go(self, raw_dir, ingest):
        _local(raw_dir)
        index = FakeIndex(indexed=12)
        result = fs.FrameworkSyncService(index).sync_framework(
            {"name": "OECD Principles", "checksum": "stale"}
        )
        assert result["status"] == "synced"
        assert ingest  # new version read first
        assert index.events == [("delete", "OECD Principles"), ("add", 2)]

    def test_a_failed_ingestion_keeps_the_indexed_version(self, raw_dir, monkeypatch):
        _local(raw_dir)

        def broken(*a, **kw):
            raise ValueError("unreadable PDF")

        monkeypatch.setattr(fs, "ingest_document", broken)
        index = FakeIndex(indexed=12)
        result = fs.FrameworkSyncService(index).sync_framework(
            {"name": "OECD Principles", "checksum": "stale"}
        )
        assert result["status"] == "error"
        assert index.events == []  # nothing deleted

    def test_a_failed_index_write_is_an_error(self, raw_dir, ingest):
        _local(raw_dir)
        result = fs.FrameworkSyncService(FakeIndex(fail_add=True)).sync_framework(
            {"name": "OECD Principles"}
        )
        assert result["status"] == "error"
        assert "index unavailable" in result["error"]

    def test_a_relative_local_path_resolves_from_the_project_root(self, raw_dir, ingest):
        # Written relative to the repository root in config/frameworks.yaml, so
        # the sync works from any working directory.
        relative = "backend/tests/golden/eu-ai-act-2024-1689.pdf"
        root = Path(fs.__file__).resolve().parents[2]
        result = fs.FrameworkSyncService(FakeIndex()).sync_framework(
            {"name": "EU AI Act", "local_path": relative}
        )
        assert result["status"] == "synced"
        assert ingest[0]["path"] == root / relative


class TestMultiRoleFrameworks:
    def test_each_role_gets_its_own_deterministic_copy(self, raw_dir, ingest):
        _local(raw_dir)
        roles = ["module_2_practical", "module_3_implementation"]
        index = FakeIndex()
        first = fs.FrameworkSyncService(index).sync_framework(
            {"name": "OECD Principles", "roles": roles}
        )
        ids_first = [c.chunk_id for c in index.added]
        fs.FrameworkSyncService(index).sync_framework({"name": "OECD Principles", "roles": roles})
        ids_second = [c.chunk_id for c in index.added]

        assert first["chunk_count"] == 4  # two chunks, two roles
        assert sorted(c.metadata["roles"] for c in index.added) == sorted(roles * 2)
        assert len(set(ids_first)) == 4
        assert ids_first == ids_second  # a re-sync keeps the ids evidence cites


class TestConfig:
    def test_the_override_path_is_used(self, tmp_path, monkeypatch):
        config = tmp_path / "frameworks.yaml"
        config.write_text("frameworks:\n  - name: A\n  - name: B\n")
        monkeypatch.setenv("FRAMEWORKS_CONFIG_PATH", str(config))
        assert [f["name"] for f in fs.load_frameworks_config()] == ["A", "B"]

    def test_the_repo_config_is_found_without_an_override(self, monkeypatch):
        monkeypatch.delenv("FRAMEWORKS_CONFIG_PATH", raising=False)
        assert fs._resolve_frameworks_config().is_file()

    def test_sync_all_visits_every_configured_framework(
        self, raw_dir, ingest, tmp_path, monkeypatch
    ):
        config = tmp_path / "frameworks.yaml"
        config.write_text("frameworks:\n  - name: A\n  - name: B\n")
        monkeypatch.setenv("FRAMEWORKS_CONFIG_PATH", str(config))
        results = fs.FrameworkSyncService(FakeIndex(indexed=3)).sync_all()
        assert [r["name"] for r in results] == ["A", "B"]
        assert all(r["status"] == "synced" for r in results)

    def test_file_hash_is_sha256(self, tmp_path):
        path = tmp_path / "x.pdf"
        path.write_bytes(PDF_BYTES)
        assert fs.compute_file_hash(path) == hashlib.sha256(PDF_BYTES).hexdigest()
