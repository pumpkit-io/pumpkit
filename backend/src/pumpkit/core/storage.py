"""
The `FileStorage` port: files the Instance keeps by key, such as Media until it is published
(ADR 0021). It lives in `core` because the backend stores files and the publisher reads them.

`LocalDirectoryStorage` keeps them in `MEDIA_STORAGE_DIR`, on a volume both services mount; an
S3-compatible provider can join it later behind the same port (ADR 0011).

Mediators reach it only through `get_file_storage`; tests override it with the same adapter on a
temporary directory, the `file_storage` fixture.
"""

import asyncio
import contextlib
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, NamedTuple, Optional, Protocol

from pumpkit.core.config import settings
from pumpkit.core.errors import AppError

# Slash-separated segments that can't be `.` or `..`, so a key never leaves the directory.
_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*(/[A-Za-z0-9_-][A-Za-z0-9._-]*)*")
_COPY_CHUNK_BYTES = 1024 * 1024
_PARTIAL_PREFIX = ".partial-"


class StoredFileNotFoundError(AppError):
    """No file is stored under the key: never stored, or already deleted."""

    status_code = 404
    public_detail = "That file isn't stored any more."

    def __init__(self, key: str) -> None:
        super().__init__(f"No file is stored under {key!r}")
        self.key = key


class StoredFile(NamedTuple):
    key: str
    modified_at: datetime


class FileStorage(Protocol):
    async def put(self, key: str, source: BinaryIO) -> None:
        """Store everything `source` reads under `key`, replacing any file already there."""
        ...

    async def open(self, key: str) -> BinaryIO:
        """The file under `key`, open for reading; the caller closes it."""
        ...

    async def delete(self, key: str) -> None:
        """Remove the file under `key`; a key with no file is already gone."""
        ...

    async def list_files(self, prefix: str) -> list[StoredFile]:
        """Every file under the directory `prefix`, such as `media/`, with when it was last written."""
        ...

    async def delete_abandoned_writes(self, prefix: str, *, written_before: datetime) -> None:
        """Delete what writes under `prefix` that stopped before `written_before` left unfinished."""
        ...


class LocalDirectoryStorage:
    """Keeps each file at `root/<key>`, making the directories it needs on first write."""

    def __init__(self, root: Path) -> None:
        self.root = root

    async def put(self, key: str, source: BinaryIO) -> None:
        await asyncio.to_thread(self._put, self._path(key), source)

    async def open(self, key: str) -> BinaryIO:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.open, "rb")
        except FileNotFoundError:
            raise StoredFileNotFoundError(key) from None

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, self._path(key))

    async def list_files(self, prefix: str) -> list[StoredFile]:
        return await asyncio.to_thread(self._list_files, prefix)

    async def delete_abandoned_writes(self, prefix: str, *, written_before: datetime) -> None:
        await asyncio.to_thread(self._delete_abandoned_writes, prefix, written_before)

    def _list_files(self, prefix: str) -> list[StoredFile]:
        found = []
        for path in (self.root / prefix).rglob("*"):
            key = path.relative_to(self.root).as_posix()
            # A partial write's name is no valid key, so only stored files are listed.
            if _KEY_PATTERN.fullmatch(key) and path.is_file():
                modified = _modified_at(path)
                if modified is not None:
                    found.append(StoredFile(key, modified))
        return found

    def _delete_abandoned_writes(self, prefix: str, written_before: datetime) -> None:
        # A put rewrites its partial file at least every chunk, so an old one's writer died.
        for path in (self.root / prefix).rglob(f"{_PARTIAL_PREFIX}*"):
            modified = _modified_at(path)
            if modified is not None and modified < written_before:
                self._delete(path)

    def _path(self, key: str) -> Path:
        if not _KEY_PATTERN.fullmatch(key):
            raise ValueError(f"Not a valid storage key: {key!r}")
        return self.root / key

    def _delete(self, path: Path) -> None:
        path.unlink(missing_ok=True)
        # Its own directory goes once empty; shared ones above stay, as a put may be making them.
        if path.parent != self.root:
            with contextlib.suppress(OSError):
                path.parent.rmdir()

    @staticmethod
    def _put(path: Path, source: BinaryIO) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside the target and renamed, so a reader never sees a half-written file.
        # The leading dot keeps the partial file's name outside every valid key.
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=_PARTIAL_PREFIX, delete=False
        ) as partial:
            try:
                shutil.copyfileobj(source, partial, _COPY_CHUNK_BYTES)
            except BaseException:
                os.unlink(partial.name)
                raise
        os.replace(partial.name, path)


def _modified_at(path: Path) -> Optional[datetime]:
    """When the file was last written, or None once it is gone."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except FileNotFoundError:
        return None


@lru_cache
def get_file_storage() -> FileStorage:
    """FastAPI dependency for the `FileStorage` port."""
    return LocalDirectoryStorage(Path(settings.MEDIA_STORAGE_DIR))
