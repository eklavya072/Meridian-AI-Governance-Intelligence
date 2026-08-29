"""Where uploaded documents and exported briefs actually live.

Uploads were written straight to container disk with `file_path.write_bytes`,
and the absolute path was persisted on the workspace row. Two consequences,
both real rather than theoretical:

  - a restart on ephemeral disk loses the file while the database still
    points at it. `run_analysis` already carries a defensive branch for
    exactly this ("The uploaded files are no longer on disk. Please upload
    them again"), which is the symptom, not the fix.
  - two API instances cannot share state, so the instance that serves the
    run may not be the one that received the upload.

This module puts one interface in front of both, selected by config:

    STORAGE_BACKEND=filesystem   (default — byte-for-byte current behaviour)
    STORAGE_BACKEND=azure

Azure specifically because UNDP's own engineering runs on it. Azurite is in
docker-compose.yml, so the Azure code path is exercised locally and in CI
with no cloud account and no credentials.

A stored reference is deliberately a plain string, and for the filesystem
backend it is the same absolute path that was stored before this module
existed — so every pending_documents row written by an older build keeps
resolving. Azure references carry an `azure://container/key` scheme, and any
reference without a scheme is read from the filesystem regardless of the
configured backend. That is what makes the switch safe to flip on a
database that already holds rows.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import structlog

logger = structlog.get_logger()

AZURE_SCHEME = "azure://"


class StorageError(RuntimeError):
    """Raised when a backend cannot satisfy a read or write."""


class Storage(ABC):
    """Byte storage addressed by an opaque reference string."""

    @abstractmethod
    def put(self, key: str, data: bytes) -> str:
        """Store `data` under `key`; return the reference to persist."""

    @abstractmethod
    def get(self, ref: str) -> bytes:
        """Read back what `put` stored."""

    @abstractmethod
    def exists(self, ref: str) -> bool:
        """True when `ref` still resolves to stored bytes."""

    @abstractmethod
    def delete(self, ref: str) -> None:
        """Remove `ref`. Missing references are not an error."""

    @contextmanager
    def local_path(self, ref: str) -> Iterator[Path]:
        """Yield a real filesystem path for `ref`.

        pypdf needs a file, not a stream, and the ingestion path is built
        around `Path`. The filesystem backend yields the file in place with
        no copy; remote backends download to a temporary file and clean it
        up on exit, so a caller cannot leak one by forgetting.
        """
        data = self.get(ref)
        suffix = Path(ref).suffix or ".pdf"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(data)
            tmp.close()
            yield Path(tmp.name)
        finally:
            Path(tmp.name).unlink(missing_ok=True)


class FilesystemStorage(Storage):
    """The original behaviour, behind the interface.

    References are absolute paths, which is what makes this a drop-in for
    rows written before the interface existed.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _resolve(self, ref: str) -> Path:
        path = Path(ref)
        return path if path.is_absolute() else self.root / ref

    def put(self, key: str, data: bytes) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def get(self, ref: str) -> bytes:
        path = self._resolve(ref)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise StorageError(f"Cannot read {ref}: {exc}") from exc

    def exists(self, ref: str) -> bool:
        return self._resolve(ref).is_file()

    def delete(self, ref: str) -> None:
        self._resolve(ref).unlink(missing_ok=True)

    @contextmanager
    def local_path(self, ref: str) -> Iterator[Path]:
        # No copy: the bytes are already a file on this filesystem, and
        # duplicating a 25MB upload per analysis would be pure waste.
        path = self._resolve(ref)
        if not path.is_file():
            raise StorageError(f"Cannot read {ref}: no such file")
        yield path


class AzureBlobStorage(Storage):
    """Azure Blob Storage, and Azurite locally — the same code path.

    Azurite speaks the real Blob API, so this class is not special-cased for
    it; the only difference is the connection string. That is the whole
    point: the Azure path is exercised on every PR rather than first meeting
    reality in production.
    """

    def __init__(self, connection_string: str, container: str) -> None:
        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise StorageError("STORAGE_BACKEND=azure needs azure-storage-blob installed.") from exc

        self.container = container
        self._service = BlobServiceClient.from_connection_string(connection_string)
        self._ensure_container()

    def _ensure_container(self) -> None:
        from azure.core.exceptions import ResourceExistsError

        try:
            self._service.create_container(self.container)
            logger.info("azure_container_created", container=self.container)
        except ResourceExistsError:
            pass
        except Exception as exc:
            raise StorageError(f"Cannot reach Azure storage: {exc}") from exc

    def _blob_name(self, ref: str) -> str:
        if ref.startswith(AZURE_SCHEME):
            _, _, rest = ref.partition(AZURE_SCHEME)
            container, _, name = rest.partition("/")
            if container != self.container:
                raise StorageError(
                    f"Reference {ref!r} belongs to container {container!r}, not {self.container!r}."
                )
            return name
        return ref

    def put(self, key: str, data: bytes) -> str:
        client = self._service.get_blob_client(self.container, key)
        try:
            client.upload_blob(data, overwrite=True)
        except Exception as exc:
            raise StorageError(f"Cannot write {key}: {exc}") from exc
        return f"{AZURE_SCHEME}{self.container}/{key}"

    def get(self, ref: str) -> bytes:
        client = self._service.get_blob_client(self.container, self._blob_name(ref))
        try:
            return client.download_blob().readall()
        except Exception as exc:
            raise StorageError(f"Cannot read {ref}: {exc}") from exc

    def exists(self, ref: str) -> bool:
        client = self._service.get_blob_client(self.container, self._blob_name(ref))
        try:
            return bool(client.exists())
        except Exception:
            return False

    def delete(self, ref: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        client = self._service.get_blob_client(self.container, self._blob_name(ref))
        try:
            client.delete_blob()
        except ResourceNotFoundError:
            pass
        except Exception as exc:
            raise StorageError(f"Cannot delete {ref}: {exc}") from exc


class HybridStorage(Storage):
    """Routes each reference to the backend that can actually serve it.

    A deployment that switches to Azure still has rows pointing at plain
    filesystem paths from before the switch. Sending those to Azure would
    turn a working analysis into a 404, so a reference with no scheme is
    read from disk regardless of the configured backend. New writes always
    go to the configured backend, so the filesystem set drains over time
    instead of being migrated in a big bang.
    """

    def __init__(self, primary: Storage, filesystem: FilesystemStorage) -> None:
        self.primary = primary
        self.filesystem = filesystem

    def _route(self, ref: str) -> Storage:
        return self.primary if ref.startswith(AZURE_SCHEME) else self.filesystem

    def put(self, key: str, data: bytes) -> str:
        return self.primary.put(key, data)

    def get(self, ref: str) -> bytes:
        return self._route(ref).get(ref)

    def exists(self, ref: str) -> bool:
        return self._route(ref).exists(ref)

    def delete(self, ref: str) -> None:
        self._route(ref).delete(ref)

    @contextmanager
    def local_path(self, ref: str) -> Iterator[Path]:
        with self._route(ref).local_path(ref) as path:
            yield path


_storage: Storage | None = None


def build_storage() -> Storage:
    """Construct the configured backend. Prefer `get_storage()`."""
    upload_dir = Path(os.getenv("UPLOAD_DIR", "./data/uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)
    filesystem = FilesystemStorage(upload_dir)

    backend = os.getenv("STORAGE_BACKEND", "filesystem").strip().lower()
    if backend in ("", "filesystem", "local", "disk"):
        logger.info("storage_backend_selected", backend="filesystem", root=str(upload_dir))
        return filesystem

    if backend in ("azure", "azure_blob", "azureblob"):
        conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip()
        if not conn:
            raise StorageError(
                "STORAGE_BACKEND=azure requires AZURE_STORAGE_CONNECTION_STRING. "
                "For local development, docker-compose.yml runs Azurite and "
                ".env.example carries its well-known development connection string."
            )
        container = os.getenv("AZURE_STORAGE_CONTAINER", "meridian-uploads").strip()
        azure = AzureBlobStorage(conn, container)
        logger.info("storage_backend_selected", backend="azure", container=container)
        # Wrapped so pre-existing filesystem references keep resolving.
        return HybridStorage(primary=azure, filesystem=filesystem)

    raise StorageError(f"Unknown STORAGE_BACKEND {backend!r}. Expected 'filesystem' or 'azure'.")


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        _storage = build_storage()
    return _storage


def reset_storage() -> None:
    """Drop the cached backend (tests, and config reloads)."""
    global _storage
    _storage = None


def free_disk_bytes(path: Path | str) -> int:
    """Bytes free on the filesystem holding `path`."""
    return shutil.disk_usage(Path(path)).free
