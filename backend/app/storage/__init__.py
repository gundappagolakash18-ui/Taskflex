"""Private file storage abstraction.

Uploaded verification documents are never exposed through a public URL —
files are read back only through an authorized endpoint.
"""

import re
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import AppException, ErrorCode

SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class StorageBackend(ABC):
    @abstractmethod
    def save(self, content: bytes, original_filename: str, content_type: str, folder: str = "documents") -> dict:
        """Persist bytes and return {path, file_name, size, mime_type}."""

    @abstractmethod
    def read(self, storage_path: str) -> bytes:
        """Read bytes for an authorized viewer."""

    @abstractmethod
    def delete(self, storage_path: str) -> None:
        """Remove a stored object."""


class LocalStorageBackend(StorageBackend):
    """Filesystem storage rooted at settings.upload_dir (private, not web-served)."""

    def __init__(self, root: str | None = None):
        self.root = Path(root or settings.upload_dir).resolve()

    def _abs(self, storage_path: str) -> Path:
        candidate = (self.root / storage_path).resolve()
        if not candidate.is_relative_to(self.root):
            raise AppException("Invalid storage path.", code=ErrorCode.VALIDATION_ERROR)
        return candidate

    def save(self, content: bytes, original_filename: str, content_type: str, folder: str = "documents") -> dict:
        safe_name = SAFE_FILENAME.sub("_", Path(original_filename).name)[:120] or "file"
        stored_name = f"{uuid.uuid4().hex}_{safe_name}"
        directory = self.root / folder
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / stored_name
        target.write_bytes(content)
        relative = (Path(folder) / stored_name).as_posix()
        return {
            "path": relative,
            "file_name": original_filename,
            "size": len(content),
            "mime_type": content_type,
        }

    def read(self, storage_path: str) -> bytes:
        path = self._abs(storage_path)
        if not path.is_file():
            raise AppException("File not found.", code=ErrorCode.NOT_FOUND, status_code=404)
        return path.read_bytes()

    def delete(self, storage_path: str) -> None:
        path = self._abs(storage_path)
        if path.is_file():
            path.unlink()


_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Swap for S3StorageBackend() in production; callers are unaffected."""
    global _storage
    if _storage is None:
        _storage = LocalStorageBackend()
    return _storage


def validate_upload(filename: str, content_type: str, size_bytes: int) -> None:
    if size_bytes > settings.max_upload_size_mb * 1024 * 1024:
        raise AppException(
            f"File exceeds the {settings.max_upload_size_mb} MB limit.",
            code=ErrorCode.FILE_TOO_LARGE,
        )
    if content_type not in settings.allowed_upload_mime_list:
        raise AppException(
            f"File type {content_type} is not allowed.",
            code=ErrorCode.FILE_TYPE_NOT_ALLOWED,
        )
    if not filename or len(filename) > 255:
        raise AppException("Invalid filename.", code=ErrorCode.VALIDATION_ERROR)
