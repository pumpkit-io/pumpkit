"""
The local-directory storage adapter, on a temporary directory as every test's `file_storage`.
"""

import io

import pytest

from pumpkit.core.storage import LocalDirectoryStorage, StoredFileNotFoundError


async def test_a_stored_file_reads_back_byte_for_byte(file_storage):
    data = bytes(range(256)) * 4096

    await file_storage.put("media/abc123", io.BytesIO(data))

    with await file_storage.open("media/abc123") as stored:
        assert stored.read() == data


async def test_storing_a_key_again_replaces_its_file(file_storage):
    await file_storage.put("abc", io.BytesIO(b"first"))
    await file_storage.put("abc", io.BytesIO(b"second"))

    with await file_storage.open("abc") as stored:
        assert stored.read() == b"second"


async def test_a_deleted_key_is_gone(file_storage):
    await file_storage.put("abc", io.BytesIO(b"bytes"))

    await file_storage.delete("abc")

    with pytest.raises(StoredFileNotFoundError, match="abc"):
        await file_storage.open("abc")


async def test_deleting_an_unknown_key_does_nothing(file_storage):
    await file_storage.delete("never-stored")


async def test_an_unknown_key_raises_a_clear_error(file_storage):
    with pytest.raises(StoredFileNotFoundError, match="No file is stored under 'nothing-here'"):
        await file_storage.open("nothing-here")


@pytest.mark.parametrize("key", ["", "../outside", "a/../../outside", "/etc/passwd", "a//b", "."])
async def test_a_key_that_could_leave_the_directory_is_refused(tmp_path, key):
    storage = LocalDirectoryStorage(tmp_path / "storage")

    with pytest.raises(ValueError, match="storage key"):
        await storage.put(key, io.BytesIO(b"bytes"))
    with pytest.raises(ValueError, match="storage key"):
        await storage.open(key)
    with pytest.raises(ValueError, match="storage key"):
        await storage.delete(key)
    assert list(tmp_path.iterdir()) == []


async def test_the_storage_directory_is_made_on_first_put(tmp_path):
    storage = LocalDirectoryStorage(tmp_path / "not" / "yet" / "there")

    await storage.put("abc", io.BytesIO(b"bytes"))

    assert (tmp_path / "not" / "yet" / "there" / "abc").read_bytes() == b"bytes"
