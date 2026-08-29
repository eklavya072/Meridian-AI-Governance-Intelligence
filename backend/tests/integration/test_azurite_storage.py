"""The Azure storage path, against a real Blob endpoint (Azurite).

These run against Azurite rather than a mock deliberately. A mocked Azure
client tests our assumptions about the SDK; Azurite tests the SDK. The
difference is where container creation, overwrite semantics and 404 handling
actually live.

Skipped unless AZURE_STORAGE_CONNECTION_STRING points somewhere reachable,
so `make test` on a laptop with nothing running stays green. CI runs Azurite
as a service container, so this executes on every push.
"""

import os
import uuid

import pytest

PDF = b"%PDF-1.4\nazurite roundtrip\n%%EOF\n"

CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")


def _azurite_reachable() -> bool:
    if not CONNECTION_STRING:
        return False
    try:
        from azure.storage.blob import BlobServiceClient

        client = BlobServiceClient.from_connection_string(CONNECTION_STRING)
        client.get_service_properties()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _azurite_reachable(),
    reason="Azurite not reachable; set AZURE_STORAGE_CONNECTION_STRING (docker compose up azurite)",
)


@pytest.fixture
def azure_storage():
    from src.storage import AzureBlobStorage

    # A container per test run, so a failed run cannot leave state that makes
    # the next one pass for the wrong reason.
    container = f"test-{uuid.uuid4().hex[:12]}"
    yield AzureBlobStorage(CONNECTION_STRING, container)


def test_container_is_created_on_first_use(azure_storage):
    # __init__ already ran _ensure_container; a write proves it took.
    ref = azure_storage.put("smoke.pdf", PDF)

    assert azure_storage.exists(ref)


def test_roundtrip_through_the_real_blob_api(azure_storage):
    ref = azure_storage.put("policy.pdf", PDF)

    assert ref.startswith("azure://")
    assert azure_storage.get(ref) == PDF


def test_local_path_downloads_and_cleans_up(azure_storage):
    ref = azure_storage.put("policy.pdf", PDF)

    with azure_storage.local_path(ref) as path:
        assert path.read_bytes() == PDF
        downloaded = path

    # The temporary file must not outlive the context — an analysis that
    # leaked one per document would fill the container's disk, which is the
    # problem blob storage was adopted to avoid.
    assert not downloaded.exists()


def test_reupload_replaces_rather_than_erroring(azure_storage):
    azure_storage.put("policy.pdf", PDF)
    azure_storage.put("policy.pdf", b"%PDF-1.4\nsecond version\n%%EOF\n")

    # Re-uploading the same filename replaces the earlier copy; the workspace
    # upload path relies on this rather than on delete-then-write, which
    # would lose the document if the write failed.
    assert b"second version" in azure_storage.get("policy.pdf")


def test_missing_blob_reports_not_existing(azure_storage):
    assert azure_storage.exists("never-written.pdf") is False


def test_reading_a_missing_blob_raises_storage_error(azure_storage):
    from src.storage import StorageError

    with pytest.raises(StorageError):
        azure_storage.get("never-written.pdf")


def test_delete_is_idempotent(azure_storage):
    ref = azure_storage.put("policy.pdf", PDF)
    azure_storage.delete(ref)
    azure_storage.delete(ref)  # must not raise

    assert azure_storage.exists(ref) is False


def test_reference_from_another_container_is_refused(azure_storage):
    from src.storage import StorageError

    # Silently reading from the wrong container would be worse than failing:
    # it would serve one tenant's document to another.
    with pytest.raises(StorageError, match="belongs to container"):
        azure_storage.get("azure://someone-elses-container/policy.pdf")


def test_hybrid_reads_legacy_filesystem_refs_while_writing_to_azure(azure_storage, tmp_path):
    from src.storage import FilesystemStorage, HybridStorage

    legacy = FilesystemStorage(tmp_path)
    old_ref = legacy.put("uploaded-before-the-switch.pdf", PDF)
    hybrid = HybridStorage(primary=azure_storage, filesystem=legacy)

    # This is the migration property, verified against a real Blob endpoint:
    # a deployment can flip STORAGE_BACKEND without stranding the uploads it
    # already accepted.
    assert hybrid.get(old_ref) == PDF
    new_ref = hybrid.put("after.pdf", PDF)
    assert new_ref.startswith("azure://")
    assert hybrid.get(new_ref) == PDF
