"""
Deleting Media nothing references any more: the publisher's pass sweeps Media that neither a
Post's Text nor a Scheduled post holds, once older than `UNREFERENCED_GRACE`, with its files, and
stored files no Media record names. Media changes through the HTTP API; the storage directory
shows what stays.
"""

import asyncio
import io
import logging
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from httpx import AsyncClient
from sqlalchemy import event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.scheduling.publisher as publisher
import pumpkit.scheduling.service as scheduling_service
from pumpkit.core.logging import logger
from pumpkit.core.storage import LocalDirectoryStorage, StoredFile, get_file_storage
from pumpkit.main import app
from pumpkit.posts.models import Media, Post
from pumpkit.scheduling.media_sweep import FILES_SWEPT_EVERY, UNREFERENCED_GRACE
from pumpkit.scheduling.publish import STUCK_AFTER
from pumpkit.x_connection.x_publisher import XPostRejectedError, XRateLimitedError
from tests.media_files import png

API = "/api/v1"
POSTS = f"{API}/posts"
SCHEDULED_POSTS = f"{API}/scheduled-posts"
LATER = "2026-10-10T14:00:00Z"
PAST_GRACE = UNREFERENCED_GRACE + timedelta(seconds=1)


async def _attach_to_text(client: AsyncClient, post_id: str, *, part: int = 1) -> str:
    response = await client.post(
        f"{POSTS}/{post_id}/text/parts/{part}/media",
        files={"file": ("photo.png", png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _remove_from_text(client: AsyncClient, post_id: str, media_id: str) -> None:
    response = await client.delete(f"{POSTS}/{post_id}/text/media/{media_id}")
    assert response.status_code == 204, response.text


async def _schedule(client: AsyncClient, post_id: str, **body) -> dict:
    response = await client.post(
        SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER, **body}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _text_media(client: AsyncClient, post_id: str) -> list[str]:
    response = await client.get(f"{POSTS}/{post_id}")
    assert response.status_code == 200, response.text
    return [m["id"] for part in response.json()["text"]["parts"] for m in part["media"]]


def _stored(file_storage) -> set[str]:
    """Every file and directory under the storage directory, relative to it."""
    root: Path = file_storage.root
    return {str(path.relative_to(root)) for path in root.rglob("*")} if root.exists() else set()


class FailingStorage(LocalDirectoryStorage):
    """The local adapter on the same directory, failing the way a test asks."""

    def __init__(
        self,
        root: Path,
        *,
        fail_put: str | None = None,
        fail_delete_of: frozenset[str] = frozenset(),
        fail_list: asyncio.Event | None = None,
        delete_error: Exception = RuntimeError("storage answered nonsense"),
    ) -> None:
        super().__init__(root)
        self.fail_put = fail_put
        self.fail_delete_of = fail_delete_of
        self.fail_list = fail_list
        self.delete_error = delete_error

    async def put(self, key: str, source: BinaryIO) -> None:
        if self.fail_put is not None and key.endswith(self.fail_put):
            raise OSError("disk full")
        await super().put(key, source)

    async def delete(self, key: str) -> None:
        if any(media_id in key for media_id in self.fail_delete_of):
            raise self.delete_error
        await super().delete(key)

    async def list_files(self, prefix: str) -> list[StoredFile]:
        if self.fail_list is not None:
            # Stops the publisher's loop after this pass, so the test needs no sleep.
            self.fail_list.set()
            raise OSError("storage unreachable")
        return await super().list_files(prefix)


def _files_of(media_id: str) -> set[str]:
    return {"media", f"media/{media_id}", f"media/{media_id}/file", f"media/{media_id}/preview"}


async def test_media_removed_from_the_text_is_deleted_with_its_files_after_the_grace_period(
    client, subscribed, fixed_clock, post_with, file_storage, db_session_maker, fake_x_publisher
):
    post_id = await post_with("One")
    media_id = await _attach_to_text(client, post_id)
    await _remove_from_text(client, post_id, media_id)
    fixed_clock.advance(PAST_GRACE)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert _stored(file_storage) == {"media"}
    preview = await client.get(f"{API}/media/{media_id}/preview")
    assert preview.status_code == 404, preview.text


async def test_media_removed_within_the_grace_period_is_kept(
    client, subscribed, fixed_clock, post_with, file_storage, db_session_maker, fake_x_publisher
):
    post_id = await post_with("One")
    media_id = await _attach_to_text(client, post_id)
    await _remove_from_text(client, post_id, media_id)
    fixed_clock.advance(UNREFERENCED_GRACE - timedelta(seconds=1))

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert _stored(file_storage) == _files_of(media_id)
    preview = await client.get(f"{API}/media/{media_id}/preview")
    assert preview.status_code == 200, preview.text


async def test_media_on_the_text_is_never_deleted_however_old(
    client, subscribed, fixed_clock, post_with, file_storage, db_session_maker, fake_x_publisher
):
    post_id = await post_with("One")
    kept = await _attach_to_text(client, post_id)
    removed = await _attach_to_text(client, post_id)
    await _remove_from_text(client, post_id, removed)
    fixed_clock.advance(timedelta(days=30))

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert _stored(file_storage) == _files_of(kept)
    assert await _text_media(client, post_id) == [kept]


async def test_media_removed_from_a_scheduled_post_is_deleted_and_the_texts_stays(
    client,
    subscribed,
    fixed_clock,
    connect_x,
    post_with,
    file_storage,
    db_session_maker,
    fake_x_publisher,
):
    await connect_x()
    post_id = await post_with("One")
    on_text = await _attach_to_text(client, post_id)
    scheduled = await _schedule(client, post_id)
    attached = await client.post(
        f"{SCHEDULED_POSTS}/{scheduled['id']}/parts/1/media",
        files={"file": ("photo.png", png(), "image/png")},
    )
    assert attached.status_code == 201, attached.text
    for media_id in (on_text, attached.json()["id"]):
        removed = await client.delete(f"{SCHEDULED_POSTS}/{scheduled['id']}/media/{media_id}")
        assert removed.status_code == 204, removed.text
    fixed_clock.advance(PAST_GRACE)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert _stored(file_storage) == _files_of(on_text)
    assert await _text_media(client, post_id) == [on_text]


async def test_media_only_a_waiting_scheduled_post_holds_is_never_deleted_however_old(
    client,
    subscribed,
    fixed_clock,
    connect_x,
    post_with,
    file_storage,
    db_session_maker,
    fake_x_publisher,
):
    await connect_x()
    post_id = await post_with("One")
    scheduled = await _schedule(client, post_id)
    attached = await client.post(
        f"{SCHEDULED_POSTS}/{scheduled['id']}/parts/1/media",
        files={"file": ("photo.png", png(), "image/png")},
    )
    assert attached.status_code == 201, attached.text
    media_id = attached.json()["id"]
    fixed_clock.advance(PAST_GRACE)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert await _text_media(client, post_id) == []
    assert _stored(file_storage) == _files_of(media_id)
    preview = await client.get(f"{API}/media/{media_id}/preview")
    assert preview.status_code == 200, preview.text


async def test_unscheduling_keeps_the_texts_media_and_deletes_the_scheduled_posts_own(
    client,
    subscribed,
    fixed_clock,
    connect_x,
    post_with,
    file_storage,
    db_session_maker,
    fake_x_publisher,
):
    await connect_x()
    post_id = await post_with("One")
    on_text = await _attach_to_text(client, post_id)
    scheduled = await _schedule(client, post_id)
    own = await client.post(
        f"{SCHEDULED_POSTS}/{scheduled['id']}/parts/1/media",
        files={"file": ("photo.png", png(), "image/png")},
    )
    assert own.status_code == 201, own.text
    unscheduled = await client.delete(f"{SCHEDULED_POSTS}/{scheduled['id']}")
    assert unscheduled.status_code == 204, unscheduled.text
    fixed_clock.advance(PAST_GRACE)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert _stored(file_storage) == _files_of(on_text)
    assert await _text_media(client, post_id) == [on_text]


async def test_a_published_posts_media_keeps_its_record_and_preview(
    client,
    subscribed,
    fixed_clock,
    connect_x,
    post_with,
    file_storage,
    db_session_maker,
    fake_x_publisher,
):
    await connect_x()
    post_id = await post_with("One")
    media_id = await _attach_to_text(client, post_id)
    published = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert published.json()["state"] == "published", published.text
    fixed_clock.advance(timedelta(days=30))

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert _stored(file_storage) == _files_of(media_id) - {f"media/{media_id}/file"}
    preview = await client.get(f"{API}/media/{media_id}/preview")
    assert preview.status_code == 200, preview.text


async def _replace_on_scheduled_post(client: AsyncClient, scheduled_post_id: str, media_id: str):
    """Removes `media_id` from the Scheduled post's own copy and attaches another to its Part 1."""
    removed = await client.delete(f"{SCHEDULED_POSTS}/{scheduled_post_id}/media/{media_id}")
    assert removed.status_code == 204, removed.text
    attached = await client.post(
        f"{SCHEDULED_POSTS}/{scheduled_post_id}/parts/1/media",
        files={"file": ("photo.png", png(), "image/png")},
    )
    assert attached.status_code == 201, attached.text
    return attached.json()["id"]


async def _due(client: AsyncClient, post_id: str, fixed_clock) -> dict:
    scheduled = await _schedule(client, post_id, publish_at="2026-10-10T12:05:00Z")
    fixed_clock.advance(timedelta(minutes=5))
    return scheduled


async def test_the_texts_media_replaced_on_the_scheduled_post_is_deleted_once_published(
    client,
    subscribed,
    fixed_clock,
    connect_x,
    post_with,
    file_storage,
    db_session_maker,
    fake_x_publisher,
):
    await connect_x()
    post_id = await post_with("One")
    replaced = await _attach_to_text(client, post_id)
    scheduled = await _due(client, post_id, fixed_clock)
    published = await _replace_on_scheduled_post(client, scheduled["id"], replaced)
    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    fixed_clock.advance(PAST_GRACE)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert _stored(file_storage) == _files_of(published) - {f"media/{published}/file"}
    assert await _text_media(client, post_id) == []


async def test_the_texts_media_replaced_on_a_failed_threads_live_part_is_deleted(
    client,
    subscribed,
    fixed_clock,
    connect_x,
    post_with,
    file_storage,
    db_session_maker,
    fake_x_publisher,
):
    await connect_x()
    post_id = await post_with("One", "Two")
    replaced = await _attach_to_text(client, post_id)
    on_failed_part = await _attach_to_text(client, post_id, part=2)
    scheduled = await _due(client, post_id, fixed_clock)
    published = await _replace_on_scheduled_post(client, scheduled["id"], replaced)
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Not allowed.")
    fake_x_publisher.fail_publish_on = 2
    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    fixed_clock.advance(PAST_GRACE)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert await _text_media(client, post_id) == [on_failed_part]
    assert _stored(file_storage) == (
        _files_of(published) - {f"media/{published}/file"} | _files_of(on_failed_part)
    )


async def test_the_texts_media_on_a_part_the_scheduled_post_dropped_is_deleted_once_published(
    client,
    subscribed,
    fixed_clock,
    connect_x,
    post_with,
    file_storage,
    db_session_maker,
    fake_x_publisher,
):
    await connect_x()
    post_id = await post_with("One", "Two")
    await _attach_to_text(client, post_id, part=2)
    scheduled = await _due(client, post_id, fixed_clock)
    for media_id in await _text_media(client, post_id):
        removed = await client.delete(f"{SCHEDULED_POSTS}/{scheduled['id']}/media/{media_id}")
        assert removed.status_code == 204, removed.text
    edited = await client.patch(f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"parts": ["One"]})
    assert edited.status_code == 200, edited.text
    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    fixed_clock.advance(PAST_GRACE)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert await _text_media(client, post_id) == []
    assert _stored(file_storage) == {"media"}


@asynccontextmanager
async def _text_media_drops_fail(db_session_maker) -> AsyncIterator[None]:
    """Every delete of a Text's Media fails in the database, like a lock wait timing out."""
    async with db_session_maker() as session:
        await session.execute(
            text(
                "CREATE TRIGGER text_media_locked BEFORE DELETE ON text_media "
                "BEGIN SELECT RAISE(ABORT, 'lock wait timed out'); END"
            )
        )
        await session.commit()
    try:
        yield
    finally:
        async with db_session_maker() as session:
            await session.execute(text("DROP TRIGGER text_media_locked"))
            await session.commit()


async def test_the_texts_media_a_failed_drop_kept_is_deleted_by_the_sweep_once_published(
    client,
    subscribed,
    fixed_clock,
    connect_x,
    post_with,
    file_storage,
    db_session_maker,
    fake_x_publisher,
):
    await connect_x()
    post_id = await post_with("One")
    replaced = await _attach_to_text(client, post_id)
    scheduled = await _due(client, post_id, fixed_clock)
    published = await _replace_on_scheduled_post(client, scheduled["id"], replaced)
    async with _text_media_drops_fail(db_session_maker):
        await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    post = await client.get(f"{POSTS}/{post_id}")
    assert post.json()["status"] == "published", post.text
    assert await _text_media(client, post_id) == [replaced]
    fixed_clock.advance(PAST_GRACE)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert await _text_media(client, post_id) == []
    assert _stored(file_storage) == _files_of(published) - {f"media/{published}/file"}


async def test_the_texts_media_a_failed_drop_kept_on_a_failed_threads_live_part_is_deleted(
    client,
    subscribed,
    fixed_clock,
    connect_x,
    post_with,
    file_storage,
    db_session_maker,
    fake_x_publisher,
):
    await connect_x()
    post_id = await post_with("One", "Two")
    replaced = await _attach_to_text(client, post_id)
    on_failed_part = await _attach_to_text(client, post_id, part=2)
    scheduled = await _due(client, post_id, fixed_clock)
    await _replace_on_scheduled_post(client, scheduled["id"], replaced)
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Not allowed.")
    fake_x_publisher.fail_publish_on = 2
    async with _text_media_drops_fail(db_session_maker):
        await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    assert await _text_media(client, post_id) == [replaced, on_failed_part]
    fixed_clock.advance(PAST_GRACE)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert await _text_media(client, post_id) == [on_failed_part]


async def test_the_texts_media_a_crashed_publish_kept_is_deleted_once_recovery_publishes(
    client,
    subscribed,
    fixed_clock,
    connect_x,
    post_with,
    file_storage,
    db_session_maker,
    fake_x_publisher,
):
    await connect_x()
    post_id = await post_with("One")
    replaced = await _attach_to_text(client, post_id)
    scheduled = await _due(client, post_id, fixed_clock)
    published = await _replace_on_scheduled_post(client, scheduled["id"], replaced)
    async with db_session_maker() as session:
        assert await scheduling_service.claim(
            session, scheduled_post_id=scheduled["id"], now=fixed_clock()
        )
        crashed = await scheduling_service.get_existing(session, scheduled_post_id=scheduled["id"])
        await scheduling_service.record_part_live(
            session, crashed.parts[0], x_post_id="1890000000000000777"
        )
        await session.commit()
    fixed_clock.advance(STUCK_AFTER + PAST_GRACE)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    post = await client.get(f"{POSTS}/{post_id}")
    assert post.json()["status"] == "published", post.text
    assert await _text_media(client, post_id) == []
    assert _stored(file_storage) == _files_of(published) - {f"media/{published}/file"}


@contextmanager
def _commit_fails_after_a_text_media_drop(db_engine) -> Iterator[None]:
    """The first commit after a delete of a Text's Media fails in the database."""
    dropped: list[bool] = []

    def seen(conn, cursor, statement, *args) -> None:
        if statement.startswith("DELETE FROM text_media") and not dropped:
            dropped.append(True)

    def commit(conn) -> None:
        if dropped == [True]:
            dropped.append(False)
            raise OperationalError("COMMIT", {}, Exception("database is locked"))

    event.listen(db_engine.sync_engine, "before_cursor_execute", seen)
    event.listen(db_engine.sync_engine, "commit", commit)
    try:
        yield
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", seen)
        event.remove(db_engine.sync_engine, "commit", commit)


async def test_a_thread_goes_on_publishing_when_the_texts_media_drop_fails_to_commit(
    client,
    subscribed,
    fixed_clock,
    connect_x,
    post_with,
    file_storage,
    db_engine,
    db_session_maker,
    fake_x_publisher,
):
    await connect_x()
    post_id = await post_with("One", "Two")
    replaced = await _attach_to_text(client, post_id)
    scheduled = await _due(client, post_id, fixed_clock)
    await _replace_on_scheduled_post(client, scheduled["id"], replaced)

    with _commit_fails_after_a_text_media_drop(db_engine):
        await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    post = await client.get(f"{POSTS}/{post_id}")
    assert post.json()["status"] == "published", post.text
    assert len(fake_x_publisher.published) == 2


async def test_a_published_file_left_behind_is_deleted_and_its_preview_kept(
    caplog,
    client,
    subscribed,
    fixed_clock,
    connect_x,
    post_with,
    file_storage,
    db_session_maker,
    fake_x_publisher,
):
    await connect_x()
    post_id = await post_with("One")
    media_id = await _attach_to_text(client, post_id)
    await _due(client, post_id, fixed_clock)
    undeletable = FailingStorage(
        file_storage.root, fail_delete_of=frozenset({media_id}), delete_error=OSError("busy")
    )
    caplog.set_level(logging.DEBUG, logger=logger.name)
    await publisher.run_pass(db_session_maker, fake_x_publisher, undeletable, fixed_clock)
    await publisher.run_pass(db_session_maker, fake_x_publisher, undeletable, fixed_clock)
    assert _stored(file_storage) == _files_of(media_id)
    failures = [r for r in caplog.records if r.getMessage().startswith("Deleting the published")]
    assert [r.levelno for r in failures] == [logging.ERROR, logging.DEBUG, logging.DEBUG]

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert _stored(file_storage) == _files_of(media_id) - {f"media/{media_id}/file"}
    preview = await client.get(f"{API}/media/{media_id}/preview")
    assert preview.status_code == 200, preview.text


async def test_the_file_of_media_a_waiting_part_still_holds_is_kept(
    client,
    subscribed,
    fixed_clock,
    connect_x,
    post_with,
    file_storage,
    db_session_maker,
    fake_x_publisher,
):
    await connect_x()
    post_id = await post_with("One", "Two")
    on_live = await _attach_to_text(client, post_id)
    on_waiting = await _attach_to_text(client, post_id, part=2)
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.fail_publish = XRateLimitedError("429")
    fake_x_publisher.fail_publish_on = 2
    undeletable = FailingStorage(
        file_storage.root, fail_delete_of=frozenset({on_live}), delete_error=OSError("busy")
    )
    await publisher.run_pass(db_session_maker, fake_x_publisher, undeletable, fixed_clock)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert _stored(file_storage) == _files_of(on_live) - {f"media/{on_live}/file"} | _files_of(
        on_waiting
    )


async def test_a_deleted_posts_media_is_deleted_with_its_files(
    client,
    subscribed,
    fixed_clock,
    post_with,
    file_storage,
    db,
    db_session_maker,
    fake_x_publisher,
):
    post_id = await post_with("One", "Two")
    first = await _attach_to_text(client, post_id, part=1)
    second = await _attach_to_text(client, post_id, part=2)
    other_post = await post_with("Other")
    kept = await _attach_to_text(client, other_post)
    # Pumpkit has no route deleting a Post yet; the Post's Text Media go with its row.
    draft = (
        await db.execute(
            select(Post).where(Post.id == post_id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    await db.delete(draft)
    await db.commit()
    fixed_clock.advance(PAST_GRACE)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert _stored(file_storage) == _files_of(kept)
    for media_id in (first, second):
        preview = await client.get(f"{API}/media/{media_id}/preview")
        assert preview.status_code == 404, preview.text


async def test_a_failing_sweep_still_completes_the_pass_and_touches_the_heartbeat(
    file_storage, db_session_maker, fake_x_publisher, fixed_clock, tmp_path
):
    heartbeat = tmp_path / "heartbeat"
    stop = asyncio.Event()
    failing = FailingStorage(file_storage.root, fail_list=stop)

    await asyncio.wait_for(
        publisher.run(
            db_session_maker,
            fake_x_publisher,
            failing,
            fixed_clock,
            poll_interval=timedelta(hours=1),
            stop=stop,
            heartbeat=heartbeat,
        ),
        timeout=5,
    )

    assert heartbeat.exists()


async def test_one_users_failing_sweep_leaves_the_next_users_sweep_to_run(
    client,
    subscribed,
    user,
    fixed_clock,
    post_with,
    file_storage,
    db,
    db_session_maker,
    fake_x_publisher,
    sign_in_as_another_subscribed_user,
):
    my_post = await post_with("Mine")
    mine = await _attach_to_text(client, my_post)
    await _remove_from_text(client, my_post, mine)
    other = await sign_in_as_another_subscribed_user()
    theirs_post = Post(
        user_id=other.id,
        brief="Seeded",
        corpus_post_ids=[],
        created_at=fixed_clock(),
        text_parts=["Theirs"],
        text_media=[],
    )
    db.add(theirs_post)
    await db.commit()
    theirs = await _attach_to_text(client, theirs_post.id)
    await _remove_from_text(client, theirs_post.id, theirs)
    # The User the sweep reaches first fails, so the other's sweep runs only if it moves on.
    first, second = (mine, theirs) if user.id < other.id else (theirs, mine)
    fixed_clock.advance(PAST_GRACE)
    failing = FailingStorage(file_storage.root, fail_delete_of=frozenset({first}))

    await publisher.run_pass(db_session_maker, fake_x_publisher, failing, fixed_clock)

    assert _stored(file_storage) == _files_of(first)
    preview = await client.get(f"{API}/media/{second}/preview")
    assert preview.status_code == 404, preview.text


def _written_at(file_storage, key: str, when: datetime) -> None:
    os.utime(file_storage.root / key, (when.timestamp(), when.timestamp()))


async def test_files_no_media_record_names_are_deleted_once_older_than_the_grace_period(
    client, subscribed, fixed_clock, post_with, file_storage, db_session_maker, fake_x_publisher
):
    kept = await _attach_to_text(client, await post_with("One"))
    for key in ("media/abandoned/file", "media/abandoned/preview", "media/recent/file"):
        await file_storage.put(key, io.BytesIO(b"bytes"))
    for key in (f"media/{kept}/file", f"media/{kept}/preview"):
        _written_at(file_storage, key, fixed_clock())
    _written_at(file_storage, "media/abandoned/file", fixed_clock())
    _written_at(file_storage, "media/abandoned/preview", fixed_clock())
    fixed_clock.advance(PAST_GRACE)
    _written_at(file_storage, "media/recent/file", fixed_clock())

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert _stored(file_storage) == _files_of(kept) | {"media/recent", "media/recent/file"}


async def test_stored_files_are_swept_at_most_once_an_hour(
    client, subscribed, post_with, fixed_clock, file_storage, db_session_maker, fake_x_publisher
):
    kept = await _attach_to_text(client, await post_with("One"))
    swept_at = await publisher.run_pass(
        db_session_maker, fake_x_publisher, file_storage, fixed_clock
    )
    await file_storage.put("media/abandoned/file", io.BytesIO(b"bytes"))
    _written_at(file_storage, "media/abandoned/file", fixed_clock() - PAST_GRACE)
    fixed_clock.advance(FILES_SWEPT_EVERY - timedelta(seconds=1))

    swept_at = await publisher.run_pass(
        db_session_maker, fake_x_publisher, file_storage, fixed_clock, files_swept_at=swept_at
    )
    stored_before = _stored(file_storage)
    fixed_clock.advance(timedelta(seconds=1))
    await publisher.run_pass(
        db_session_maker, fake_x_publisher, file_storage, fixed_clock, files_swept_at=swept_at
    )

    assert stored_before == _files_of(kept) | {"media/abandoned", "media/abandoned/file"}
    assert _stored(file_storage) == _files_of(kept)


async def test_partial_writes_older_than_the_grace_period_are_deleted_and_fresh_ones_kept(
    client, subscribed, fixed_clock, post_with, file_storage, db_session_maker, fake_x_publisher
):
    kept = await _attach_to_text(client, await post_with("One"))
    for key in (f"media/{kept}/file", f"media/{kept}/preview"):
        _written_at(file_storage, key, fixed_clock())
    for key in ("media/dead/.partial-a1", "media/writing/.partial-b2"):
        (file_storage.root / key).parent.mkdir(parents=True)
        (file_storage.root / key).write_bytes(b"half")
    _written_at(file_storage, "media/dead/.partial-a1", fixed_clock())
    fixed_clock.advance(PAST_GRACE)
    _written_at(file_storage, "media/writing/.partial-b2", fixed_clock())

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert _stored(file_storage) == _files_of(kept) | {
        "media/writing",
        "media/writing/.partial-b2",
    }


async def test_no_file_is_deleted_while_the_database_holds_no_media_at_all(
    fixed_clock, file_storage, db_session_maker, fake_x_publisher
):
    # A publisher pointed at the wrong database would otherwise delete every stored file.
    await file_storage.put("media/elsewhere/file", io.BytesIO(b"bytes"))
    _written_at(file_storage, "media/elsewhere/file", fixed_clock() - PAST_GRACE)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert _stored(file_storage) == {"media", "media/elsewhere", "media/elsewhere/file"}


def _commit_lost_once_media_is_committed(monkeypatch) -> None:
    """The first commit holding a Media applies, then raises, like a connection reset after COMMIT."""
    real_commit = AsyncSession.commit
    lost: list[bool] = []

    async def commit(self: AsyncSession) -> None:
        holds_media = any(isinstance(o, Media) for o in self.identity_map.values())
        await real_commit(self)
        if holds_media and not lost:
            lost.append(True)
            raise ConnectionResetError("connection reset after COMMIT")

    monkeypatch.setattr(AsyncSession, "commit", commit)


async def test_an_attach_whose_commit_applies_then_fails_keeps_the_files_of_its_media(
    client, subscribed, post_with, file_storage, monkeypatch
):
    post_id = await post_with("One")
    _commit_lost_once_media_is_committed(monkeypatch)

    response = await client.post(
        f"{POSTS}/{post_id}/text/parts/1/media",
        files={"file": ("photo.png", png(), "image/png")},
    )

    assert response.status_code == 500, response.text
    [media_id] = await _text_media(client, post_id)
    assert _stored(file_storage) == _files_of(media_id)


async def test_a_scheduled_post_attach_whose_commit_applies_then_fails_keeps_the_files(
    client, subscribed, fixed_clock, connect_x, post_with, file_storage, monkeypatch
):
    await connect_x()
    scheduled = await _schedule(client, await post_with("One"))
    _commit_lost_once_media_is_committed(monkeypatch)

    response = await client.post(
        f"{SCHEDULED_POSTS}/{scheduled['id']}/parts/1/media",
        files={"file": ("photo.png", png(), "image/png")},
    )

    assert response.status_code == 500, response.text
    [media_id] = [p.name for p in (file_storage.root / "media").iterdir()]
    assert _stored(file_storage) == _files_of(media_id)
    preview = await client.get(f"{API}/media/{media_id}/preview")
    assert preview.status_code == 200, preview.text


async def test_an_attach_that_fails_after_storing_the_file_leaves_no_file_behind(
    client, subscribed, post_with, file_storage
):
    post_id = await post_with("One")
    app.dependency_overrides[get_file_storage] = lambda: FailingStorage(
        file_storage.root, fail_put="/preview"
    )

    response = await client.post(
        f"{POSTS}/{post_id}/text/parts/1/media",
        files={"file": ("photo.png", png(), "image/png")},
    )

    assert response.status_code == 500, response.text
    assert _stored(file_storage) <= {"media"}
    assert await _text_media(client, post_id) == []


async def test_an_attach_to_a_scheduled_post_refused_after_storing_leaves_no_file_behind(
    client, subscribed, fixed_clock, connect_x, post_with, file_storage, monkeypatch
):
    await connect_x()
    scheduled = await _schedule(client, await post_with("One"))

    # The publisher claims the Scheduled post while the upload is stored.
    async def claimed_meanwhile(*args, **kwargs) -> bool:
        return False

    monkeypatch.setattr(scheduling_service, "edit", claimed_meanwhile)

    response = await client.post(
        f"{SCHEDULED_POSTS}/{scheduled['id']}/parts/1/media",
        files={"file": ("photo.png", png(), "image/png")},
    )

    assert response.status_code == 409, response.text
    assert _stored(file_storage) <= {"media"}
