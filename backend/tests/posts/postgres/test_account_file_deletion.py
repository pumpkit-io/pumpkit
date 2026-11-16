"""
Two deleted accounts' file sweeps at once: each locks only its own queued files, so one sweep
holding its rows doesn't leave the other's files on disk.
"""

import asyncio
from io import BytesIO

import pytest

from pumpkit.account_deletion import delete_files
from pumpkit.posts.models import AccountFileDeletion

pytestmark = pytest.mark.postgres

ADA, GRACE = "media/ada/photo", "media/grace/photo"


async def test_a_sweep_deletes_its_files_while_another_is_midway(
    writing_session_maker, file_storage, monkeypatch
):
    await file_storage.put(ADA, BytesIO(b"ada"))
    await file_storage.put(GRACE, BytesIO(b"grace"))
    async with writing_session_maker() as db:
        db.add_all([AccountFileDeletion(key=ADA), AccountFileDeletion(key=GRACE)])
        await db.commit()
    entered, release = asyncio.Event(), asyncio.Event()
    delete = file_storage.delete

    async def paused_on_ada(key):
        if key == ADA:
            entered.set()
            await asyncio.wait_for(release.wait(), 10)
        await delete(key)

    monkeypatch.setattr(file_storage, "delete", paused_on_ada)

    async def sweep(key):
        async with writing_session_maker() as db:
            await delete_files(db, file_storage, only_keys=frozenset({key}))

    ada_sweep = asyncio.create_task(sweep(ADA))
    await asyncio.wait_for(entered.wait(), 10)
    try:
        await sweep(GRACE)
    finally:
        release.set()
        await ada_sweep

    assert await file_storage.list_files("media") == []
