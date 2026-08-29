"""Storage interface behaviour, and the migration property that matters.

The interesting case is not "can it write a file". It is whether switching
STORAGE_BACKEND on a database that already holds absolute-path references
keeps those analyses runnable. If it does not, the flag is unusable on any
deployment that has ever accepted an upload.
"""

import pytest

from src.storage import (
    AZURE_SCHEME,
    FilesystemStorage,
    HybridStorage,
    Storage,
    StorageError,
    build_storage,
    reset_storage,
)

PDF = b"%PDF-1.4\nfake but plausible\n%%EOF\n"


@pytest.fixture
def fs(tmp_path):
    return FilesystemStorage(tmp_path / "uploads")


class _MemoryStorage(Storage):
    """Stands in for Azure so the routing tests need no network."""

    def __init__(self, container="meridian-uploads"):
        self.container = container
        self.blobs: dict[str, bytes] = {}

    def _name(self, ref):
        return ref[len(AZURE_SCHEME) + len(self.container) + 1 :] if AZURE_SCHEME in ref else ref

    def put(self, key, data):
        self.blobs[key] = data
        return f"{AZURE_SCHEME}{self.container}/{key}"

    def get(self, ref):
        try:
            return self.blobs[self._name(ref)]
        except KeyError as exc:
            raise StorageError(f"Cannot read {ref}") from exc

    def exists(self, ref):
        return self._name(ref) in self.blobs

    def delete(self, ref):
        self.blobs.pop(self._name(ref), None)


class TestFilesystemStorage:
    def test_roundtrip(self, fs):
        ref = fs.put("doc.pdf", PDF)

        assert fs.get(ref) == PDF
        assert fs.exists(ref)

    def test_reference_is_an_absolute_path(self, fs):
        # Load-bearing for backwards compatibility: rows written before this
        # module existed hold exactly this shape.
        ref = fs.put("doc.pdf", PDF)

        assert ref.startswith("/")
        assert ref.endswith("doc.pdf")

    def test_local_path_does_not_copy(self, fs):
        ref = fs.put("doc.pdf", PDF)

        with fs.local_path(ref) as path:
            assert str(path) == ref
            assert path.read_bytes() == PDF

        # Still there afterwards — no temporary file was cleaned up over it.
        assert fs.exists(ref)

    def test_missing_reference_is_not_ready(self, fs):
        assert fs.exists("/nowhere/at/all.pdf") is False

    def test_reading_a_missing_reference_raises_storage_error(self, fs):
        with pytest.raises(StorageError):
            fs.get("/nowhere/at/all.pdf")

    def test_delete_is_idempotent(self, fs):
        ref = fs.put("doc.pdf", PDF)
        fs.delete(ref)
        fs.delete(ref)  # must not raise

        assert not fs.exists(ref)


class TestHybridRouting:
    """The property that makes STORAGE_BACKEND safe to flip."""

    def test_pre_existing_filesystem_references_still_resolve(self, tmp_path):
        legacy = FilesystemStorage(tmp_path / "uploads")
        old_ref = legacy.put("uploaded-before-the-switch.pdf", PDF)

        hybrid = HybridStorage(primary=_MemoryStorage(), filesystem=legacy)

        # The deployment is now on Azure, but this row predates the switch.
        assert hybrid.exists(old_ref)
        assert hybrid.get(old_ref) == PDF
        with hybrid.local_path(old_ref) as path:
            assert path.read_bytes() == PDF

    def test_new_writes_go_to_the_primary_backend(self, tmp_path):
        legacy = FilesystemStorage(tmp_path / "uploads")
        memory = _MemoryStorage()
        hybrid = HybridStorage(primary=memory, filesystem=legacy)

        ref = hybrid.put("new.pdf", PDF)

        assert ref.startswith(AZURE_SCHEME)
        assert "new.pdf" in memory.blobs
        assert not (tmp_path / "uploads" / "new.pdf").exists()

    def test_azure_references_are_not_looked_for_on_disk(self, tmp_path):
        hybrid = HybridStorage(primary=_MemoryStorage(), filesystem=FilesystemStorage(tmp_path))

        assert hybrid.exists(f"{AZURE_SCHEME}meridian-uploads/absent.pdf") is False


class TestBackendSelection:
    def setup_method(self):
        reset_storage()

    def teardown_method(self):
        reset_storage()

    def test_defaults_to_filesystem(self, tmp_path, monkeypatch):
        monkeypatch.delenv("STORAGE_BACKEND", raising=False)
        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

        assert isinstance(build_storage(), FilesystemStorage)

    def test_azure_without_a_connection_string_fails_loudly(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "azure")
        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "")

        # Silently falling back to the filesystem would be worse: uploads
        # would land on container disk while the operator believes they are
        # in blob storage, and the data loss would only surface on restart.
        with pytest.raises(StorageError, match="AZURE_STORAGE_CONNECTION_STRING"):
            build_storage()

    def test_unknown_backend_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

        with pytest.raises(StorageError, match="Unknown STORAGE_BACKEND"):
            build_storage()
