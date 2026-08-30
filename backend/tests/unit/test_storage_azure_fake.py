"""The Azure code path, with the SDK faked.

tests/integration/test_azurite_storage.py runs this against a real Blob
endpoint, which is the stronger test — but it is skipped unless Azurite is
reachable, so on a laptop the entire Azure branch was unexercised. These run
everywhere and cover the error handling, which is the part most likely to be
wrong and least likely to be hit by a happy-path integration test.
"""

import sys
import types

import pytest

from src.storage import AZURE_SCHEME, FilesystemStorage, HybridStorage, StorageError

PDF = b"%PDF-1.4\nazure\n%%EOF\n"


# ── A fake azure.storage.blob ───────────────────────────────────────────
class ResourceExistsError(Exception):
    pass


class ResourceNotFoundError(Exception):
    pass


class _FakeBlobClient:
    def __init__(self, store, container, name, fail=None):
        self.store = store
        self.container = container
        self.name = name
        self.fail = fail

    def upload_blob(self, data, overwrite=False):
        if self.fail == "upload":
            raise RuntimeError("network died mid-upload")
        self.store[(self.container, self.name)] = data

    def download_blob(self):
        if self.fail == "download":
            raise RuntimeError("network died mid-download")
        try:
            payload = self.store[(self.container, self.name)]
        except KeyError as exc:
            raise ResourceNotFoundError(self.name) from exc
        return types.SimpleNamespace(readall=lambda: payload)

    def exists(self):
        if self.fail == "exists":
            raise RuntimeError("cannot reach storage")
        return (self.container, self.name) in self.store

    def delete_blob(self):
        if self.fail == "delete":
            raise RuntimeError("cannot delete")
        if (self.container, self.name) not in self.store:
            raise ResourceNotFoundError(self.name)
        del self.store[(self.container, self.name)]


class _FakeBlobServiceClient:
    def __init__(self, store=None, fail=None, container_exists=False):
        self.store = store if store is not None else {}
        self.fail = fail
        self.containers = {"existing"} if container_exists else set()

    @classmethod
    def from_connection_string(cls, conn):
        if "broken" in conn:
            raise RuntimeError("malformed connection string")
        return cls()

    def create_container(self, name):
        if self.fail == "create_container":
            raise RuntimeError("storage account unreachable")
        if name in self.containers:
            raise ResourceExistsError(name)
        self.containers.add(name)

    def get_blob_client(self, container, name):
        return _FakeBlobClient(self.store, container, name, fail=self.fail)


@pytest.fixture(autouse=True)
def _fake_azure_sdk(monkeypatch):
    """Install a fake azure.storage.blob / azure.core.exceptions."""
    blob_mod = types.ModuleType("azure.storage.blob")
    blob_mod.BlobServiceClient = _FakeBlobServiceClient
    core_mod = types.ModuleType("azure.core.exceptions")
    core_mod.ResourceExistsError = ResourceExistsError
    core_mod.ResourceNotFoundError = ResourceNotFoundError

    azure = types.ModuleType("azure")
    storage = types.ModuleType("azure.storage")
    core = types.ModuleType("azure.core")

    for name, mod in {
        "azure": azure,
        "azure.storage": storage,
        "azure.storage.blob": blob_mod,
        "azure.core": core,
        "azure.core.exceptions": core_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    yield


def _storage(**kw):
    from src.storage import AzureBlobStorage

    store = AzureBlobStorage("DefaultEndpointsProtocol=http;fake", "meridian-uploads")
    if kw.get("fail"):
        store._service.fail = kw["fail"]
    return store


class TestRoundTrip:
    def test_put_returns_a_scheme_qualified_reference(self):
        ref = _storage().put("policy.pdf", PDF)

        assert ref == f"{AZURE_SCHEME}meridian-uploads/policy.pdf"

    def test_get_returns_what_put_stored(self):
        s = _storage()
        ref = s.put("policy.pdf", PDF)

        assert s.get(ref) == PDF

    def test_a_bare_key_resolves_as_well_as_a_full_reference(self):
        s = _storage()
        s.put("policy.pdf", PDF)

        assert s.get("policy.pdf") == PDF

    def test_exists_is_true_after_put_and_false_after_delete(self):
        s = _storage()
        ref = s.put("policy.pdf", PDF)
        assert s.exists(ref)

        s.delete(ref)

        assert not s.exists(ref)

    def test_local_path_writes_a_real_file_and_removes_it(self):
        s = _storage()
        ref = s.put("policy.pdf", PDF)

        with s.local_path(ref) as path:
            assert path.read_bytes() == PDF
            leaked = path

        # An analysis that leaked one temp file per document would fill the
        # container disk — the problem blob storage was adopted to avoid.
        assert not leaked.exists()


class TestContainerCreation:
    def test_an_existing_container_is_not_an_error(self):
        from src.storage import AzureBlobStorage

        service = _FakeBlobServiceClient(container_exists=True)
        # Constructing against an existing container must be idempotent;
        # every process start calls this.
        store = AzureBlobStorage.__new__(AzureBlobStorage)
        store.container = "existing"
        store._service = service
        store._ensure_container()

    def test_an_unreachable_account_raises_storage_error(self):
        from src.storage import AzureBlobStorage

        store = AzureBlobStorage.__new__(AzureBlobStorage)
        store.container = "c"
        store._service = _FakeBlobServiceClient(fail="create_container")

        with pytest.raises(StorageError, match="Cannot reach Azure storage"):
            store._ensure_container()


class TestErrorHandling:
    def test_a_failed_upload_raises_storage_error_not_a_raw_sdk_error(self):
        # Callers handle StorageError; an SDK exception leaking through would
        # surface as a 500 with a stack trace.
        with pytest.raises(StorageError, match="Cannot write"):
            _storage(fail="upload").put("policy.pdf", PDF)

    def test_a_failed_download_raises_storage_error(self):
        with pytest.raises(StorageError, match="Cannot read"):
            _storage(fail="download").get("policy.pdf")

    def test_a_missing_blob_reads_as_a_storage_error(self):
        with pytest.raises(StorageError):
            _storage().get("never-written.pdf")

    def test_exists_returns_false_rather_than_raising_when_storage_is_down(self):
        # Readiness and the run endpoint both call exists(); a raise there
        # turns a degraded backend into a 500.
        assert _storage(fail="exists").exists("policy.pdf") is False

    def test_deleting_a_missing_blob_is_not_an_error(self):
        _storage().delete("never-written.pdf")

    def test_a_failed_delete_raises_storage_error(self):
        s = _storage()
        s.put("policy.pdf", PDF)
        s._service.fail = "delete"

        with pytest.raises(StorageError, match="Cannot delete"):
            s.delete("policy.pdf")


class TestContainerIsolation:
    def test_a_reference_from_another_container_is_refused(self):
        # Serving one tenant's document to another would be far worse than
        # failing the read.
        with pytest.raises(StorageError, match="belongs to container"):
            _storage().get(f"{AZURE_SCHEME}someone-else/policy.pdf")

    def test_the_refusal_names_both_containers(self):
        with pytest.raises(StorageError) as exc:
            _storage().exists(f"{AZURE_SCHEME}someone-else/policy.pdf")

        assert "someone-else" in str(exc.value)
        assert "meridian-uploads" in str(exc.value)


class TestHybridWithAzure:
    def test_legacy_filesystem_references_bypass_azure_entirely(self, tmp_path):
        legacy = FilesystemStorage(tmp_path)
        old_ref = legacy.put("before-the-switch.pdf", PDF)
        azure = _storage(fail="download")  # would raise if it were consulted
        hybrid = HybridStorage(primary=azure, filesystem=legacy)

        assert hybrid.get(old_ref) == PDF

    def test_new_writes_go_to_azure(self, tmp_path):
        hybrid = HybridStorage(primary=_storage(), filesystem=FilesystemStorage(tmp_path))

        assert hybrid.put("new.pdf", PDF).startswith(AZURE_SCHEME)

    def test_delete_routes_by_reference_scheme(self, tmp_path):
        legacy = FilesystemStorage(tmp_path)
        old_ref = legacy.put("old.pdf", PDF)
        hybrid = HybridStorage(primary=_storage(), filesystem=legacy)

        hybrid.delete(old_ref)

        assert not legacy.exists(old_ref)


class TestBackendSelectionWiring:
    def test_azure_backend_is_constructed_from_the_environment(self, monkeypatch, tmp_path):
        from src.storage import build_storage, reset_storage

        reset_storage()
        monkeypatch.setenv("STORAGE_BACKEND", "azure")
        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
        monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=http;fake")
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "custom-container")

        storage = build_storage()

        # Wrapped in HybridStorage so pre-existing filesystem rows resolve.
        assert isinstance(storage, HybridStorage)
        assert storage.primary.container == "custom-container"
        reset_storage()

    def test_get_storage_caches_the_backend(self, monkeypatch, tmp_path):
        from src.storage import get_storage, reset_storage

        reset_storage()
        monkeypatch.setenv("STORAGE_BACKEND", "filesystem")
        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

        assert get_storage() is get_storage()
        reset_storage()
