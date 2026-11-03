"""
Deleting Media nothing references any more: the publisher's pass sweeps Media that neither a
Post's Text nor a Scheduled post holds, once older than `UNREFERENCED_GRACE`, with its files.
Media changes through the HTTP API; the storage directory shows what stays.
"""

import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy import select

import pumpkit.scheduling.publisher as publisher
from pumpkit.posts.models import Post
from pumpkit.scheduling.media_sweep import UNREFERENCED_GRACE
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
    monkeypatch, file_storage, db_session_maker, fake_x_publisher, fixed_clock, tmp_path
):
    monkeypatch.setattr(
        publisher, "delete_unreferenced_media", AsyncMock(side_effect=RuntimeError("db gone"))
    )
    heartbeat = tmp_path / "heartbeat"
    stop = asyncio.Event()

    looping = asyncio.create_task(
        publisher.run(
            db_session_maker,
            fake_x_publisher,
            file_storage,
            fixed_clock,
            poll_interval=timedelta(milliseconds=10),
            stop=stop,
            heartbeat=heartbeat,
        )
    )
    await asyncio.sleep(0.2)
    stop.set()
    await asyncio.wait_for(looping, timeout=1)

    assert heartbeat.exists()
