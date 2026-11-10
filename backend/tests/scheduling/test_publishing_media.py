"""
Scheduling and publishing a Text with images (ADR 0021): each Part's Media is copied onto the
Scheduled post, uploaded to X just before that Part's X post, and deleted once it is live.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import update

import pumpkit.scheduling.publish as publish_module
from pumpkit.core.storage import StoredFileNotFoundError
from pumpkit.posts.media import file_key, preview_key
from pumpkit.posts.models import Media, TextMedia
from pumpkit.scheduling.publisher import run_pass
from pumpkit.scheduling.publishing import recover_stuck
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_publisher import (
    XMediaRefusedError,
    XMediaUnavailableError,
    XNotReceivedError,
    XPostRejectedError,
    XRateLimitedError,
    XReconnectNeededError,
)
from tests.media_files import png

POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
LATER = "2026-10-10T14:00:00Z"
RECONNECT_REASON = (
    "Not published: X no longer accepts Pumpkit's access to your account. Reconnect X, then "
    "reschedule it."
)


async def _attach(client: AsyncClient, post_id: str, data: bytes, *, part: int = 1) -> dict:
    response = await client.post(
        f"{POSTS}/{post_id}/text/parts/{part}/media",
        files={"file": ("photo.png", data, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _schedule(client: AsyncClient, post_id: str, **body):
    return await client.post(
        SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER, **body}
    )


def _media(scheduled_post: dict) -> list[list[str]]:
    return [[m["id"] for m in part["media"]] for part in scheduled_post["parts"]]


async def test_scheduling_copies_each_parts_images_in_order(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One", "Two")
    first = await _attach(client, post_id, png(40, 30))
    second = await _attach(client, post_id, png(30, 40))
    third = await _attach(client, post_id, png(), part=2)

    response = await _schedule(client, post_id)

    assert response.status_code == 201, response.text
    scheduled_post = response.json()
    assert _media(scheduled_post) == [[first["id"], second["id"]], [third["id"]]]
    assert scheduled_post["parts"][0]["media"][0] == first
    read = (await client.get(f"{POSTS}/{post_id}")).json()
    assert _media(read["scheduled_post"]) == [[first["id"], second["id"]], [third["id"]]]


async def test_a_part_over_xs_media_rule_is_refused_naming_the_part(
    client, db, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One", "Two")
    for _ in range(4):
        await _attach(client, post_id, png())
    moved = await _attach(client, post_id, png(), part=2)
    # Feedback that drops a Part can leave one over the rule; here a Media is moved by hand.
    await db.execute(
        update(TextMedia).where(TextMedia.media_id == moved["id"]).values(part_index=0, position=9)
    )
    await db.commit()

    response = await _schedule(client, post_id)

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "MEDIA_OVER_X_RULE"
    assert response.json()["detail"] == (
        "Part 1 has more media than X takes. X takes up to 4 images, or 1 GIF, or 1 video, per post."
    )
    assert (await client.get(f"{POSTS}/{post_id}")).json()["scheduled_post"] is None


async def _due(client: AsyncClient, post_id: str, fixed_clock) -> dict:
    response = await client.post(
        SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": "2026-10-10T12:05:00Z"}
    )
    assert response.status_code == 201, response.text
    fixed_clock.advance(timedelta(minutes=5))
    return response.json()


async def _scheduled_post(client: AsyncClient, post_id: str) -> dict:
    return (await client.get(f"{POSTS}/{post_id}")).json()["scheduled_post"]


async def test_the_publisher_uploads_each_parts_images_and_sends_them_with_its_x_post(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("One", "Two", "Three")
    first, second = png(40, 30), png(30, 40)
    await _attach(client, post_id, first)
    await _attach(client, post_id, second)
    await _attach(client, post_id, png(), part=3)
    await _due(client, post_id, fixed_clock)

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"
    assert [(u.access_token, u.content_type, u.category) for u in fake_x_publisher.uploads] == [
        ("access-1001-1", "image/png", "tweet_image")
    ] * 3
    assert [u.data for u in fake_x_publisher.uploads[:2]] == [first, second]
    ids = [u.media_id for u in fake_x_publisher.uploads]
    assert fake_x_publisher.published_media == [[ids[0], ids[1]], [], [ids[2]]]


async def test_once_a_part_is_live_its_files_are_deleted_and_its_preview_stays(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("One", "Two")
    on_live = await _attach(client, post_id, png())
    on_failed = await _attach(client, post_id, png(), part=2)
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Not allowed.")
    fake_x_publisher.fail_publish_on = 2

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    with pytest.raises(StoredFileNotFoundError):
        await file_storage.open(file_key(on_live["id"]))
    (await file_storage.open(preview_key(on_live["id"]))).close()
    (await file_storage.open(file_key(on_failed["id"]))).close()
    preview = await client.get(f"/api/v1{on_live['preview_url']}")
    assert preview.status_code == 200
    scheduled_post = await _scheduled_post(client, post_id)
    assert scheduled_post["state"] == "failed"
    assert _media(scheduled_post) == [[on_live["id"]], [on_failed["id"]]]


async def test_a_thread_resumes_without_uploading_live_parts_media_again(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("One", "Two")
    await _attach(client, post_id, png())
    await _attach(client, post_id, png(), part=2)
    scheduled_post = await _due(client, post_id, fixed_clock)
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Try again.")
    fake_x_publisher.fail_publish_on = 2
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    fake_x_publisher.fail_publish = None
    added = await _attach(client, post_id, png(), part=2)

    retried = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled_post['id']}", json={"copy_text": True, "publish_now": True}
    )

    assert retried.status_code == 200, retried.text
    assert retried.json()["state"] == "published"
    assert len(fake_x_publisher.uploads) == 4
    ids = [u.media_id for u in fake_x_publisher.uploads]
    assert fake_x_publisher.published_media == [[ids[0]], [ids[1]], [ids[2], ids[3]]]
    assert _media(retried.json())[1][-1] == added["id"]


@pytest.mark.parametrize(
    "error",
    [
        XRateLimitedError("429"),
        XMediaUnavailableError("X answered HTTP 503 uploading media"),
        XNotReceivedError("refused connection"),
    ],
)
async def test_an_upload_x_didnt_take_retries_in_the_window_with_nothing_published(
    error,
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("With a picture")
    await _attach(client, post_id, png())
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.fail_upload = error

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    waiting = await _scheduled_post(client, post_id)
    assert waiting["state"] == "scheduled"
    assert fake_x_publisher.published == []

    fake_x_publisher.fail_upload = None
    fixed_clock.advance(timedelta(minutes=1))
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"
    assert len(fake_x_publisher.published_media[0]) == 1


async def test_an_upload_x_refuses_fails_the_post_with_xs_reason_naming_the_part(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("One", "Two")
    await _attach(client, post_id, png(), part=2)
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.fail_upload = XMediaRefusedError(400, "Unsupported image.")

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    failed = await _scheduled_post(client, post_id)
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == "X refused the media on part 2: Unsupported image."
    assert [p["live"] for p in failed["parts"]] == [True, False]
    assert len(fake_x_publisher.published) == 1


async def test_an_upload_x_refuses_the_token_for_needs_a_reconnect(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("With a picture")
    await _attach(client, post_id, png())
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.fail_upload = XReconnectNeededError("401")

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    failed = await _scheduled_post(client, post_id)
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == RECONNECT_REASON
    assert fake_x_publisher.published == []
    assert (await client.get("/api/v1/x-connection")).json()["needs_reconnect"] is True


async def test_post_now_with_images_publishes_within_the_request(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Right now")
    await _attach(client, post_id, png())

    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})

    assert response.status_code == 201, response.text
    assert response.json()["state"] == "published"
    assert fake_x_publisher.published_media == [[fake_x_publisher.uploads[0].media_id]]


async def test_publish_events_say_whether_the_post_carried_media(
    client,
    subscribed,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
    monkeypatch,
):
    captured = MagicMock()
    monkeypatch.setattr(publish_module, "posthog_client", captured)
    await connect_x()
    with_media = await post_with("With a picture")
    await _attach(client, with_media, png())
    await client.post(SCHEDULED_POSTS, json={"post_id": with_media, "publish_now": True})
    fake_x_publisher.fail_publish = XPostRejectedError(400, "No.")
    await client.post(
        SCHEDULED_POSTS, json={"post_id": await post_with("Words only"), "publish_now": True}
    )

    published, failed = captured.capture.call_args_list
    assert published.args[0] == "scheduled_post_published"
    assert published.kwargs["properties"]["has_media"] is True
    assert failed.args[0] == "scheduled_post_failed"
    assert failed.kwargs["properties"]["has_media"] is False


async def test_editing_the_parts_of_a_scheduled_post_keeps_each_parts_media_in_place(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One", "Two")
    first = await _attach(client, post_id, png())
    second = await _attach(client, post_id, png(), part=2)
    scheduled_post = (await _schedule(client, post_id)).json()

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled_post['id']}", json={"parts": ["One", "Two, again"]}
    )

    assert response.status_code == 200, response.text
    assert _media(response.json()) == [[first["id"]], [second["id"]]]


@pytest.mark.parametrize("parts", [["One", "Three"], ["One", "Two", "Three", "Four"]])
async def test_an_edit_adding_or_removing_parts_is_refused_while_a_part_has_media(
    parts, client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One", "Two", "Three")
    on_two = await _attach(client, post_id, png(), part=2)
    scheduled_post = (await _schedule(client, post_id)).json()

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled_post['id']}", json={"parts": parts}
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "MEDIA_PART_COUNT"
    assert response.json()["detail"] == (
        "Part 2 has media, so this edit can't add or remove parts. Remove the media first, or "
        "change the post's text and copy it onto the scheduled post."
    )
    assert _media(await _scheduled_post(client, post_id)) == [[], [on_two["id"]], []]


async def test_an_edit_adding_or_removing_parts_goes_through_without_media(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One", "Two", "Three")
    scheduled_post = (await _schedule(client, post_id)).json()

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled_post['id']}", json={"parts": ["One", "Three"]}
    )

    assert response.status_code == 200, response.text
    assert _media(response.json()) == [[], []]


async def test_media_that_already_went_out_is_refused_when_scheduling_again(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("One", "Two")
    await _attach(client, post_id, png())
    scheduled_post = await _due(client, post_id, fixed_clock)
    fake_x_publisher.fail_publish = XPostRejectedError(400, "No.")
    fake_x_publisher.fail_publish_on = 2
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    await client.delete(f"{SCHEDULED_POSTS}/{scheduled_post['id']}")

    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "MEDIA_GONE"
    assert response.json()["detail"] == (
        "Part 1 has media that already went out on X, so Pumpkit no longer keeps it. "
        "Remove it and attach the file again."
    )


def _recovering_after(fake_x_publisher, db_session_maker, fixed_clock, wait: timedelta):
    """A call to X during which `wait` passes and another publisher pass recovers stuck posts."""

    async def recover() -> None:
        fixed_clock.advance(wait)
        async with db_session_maker() as session:
            await recover_stuck(session, now=fixed_clock())

    return recover


async def test_a_publish_renews_its_claim_before_each_upload_so_recovery_leaves_it_be(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("Two pictures")
    await _attach(client, post_id, png())
    await _attach(client, post_id, png())
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.while_uploading = _recovering_after(
        fake_x_publisher, db_session_maker, fixed_clock, timedelta(minutes=6)
    )

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    published = await _scheduled_post(client, post_id)
    assert published["state"] == "published"
    assert published["failed_reason"] is None
    assert len(fake_x_publisher.published_media[0]) == 2


async def test_a_publish_recovery_failed_meanwhile_sends_nothing_more_and_stays_failed(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("A picture")
    await _attach(client, post_id, png())
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.while_uploading = _recovering_after(
        fake_x_publisher, db_session_maker, fixed_clock, timedelta(minutes=11)
    )

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    failed = await _scheduled_post(client, post_id)
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == publish_module.OUTCOME_UNKNOWN_REASON
    assert fake_x_publisher.published == []


async def test_a_part_x_took_after_recovery_failed_the_post_leaves_the_failure_as_it_was(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("One", "Two")
    await _attach(client, post_id, png())
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.while_publishing = _recovering_after(
        fake_x_publisher, db_session_maker, fixed_clock, timedelta(minutes=11)
    )

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    failed = await _scheduled_post(client, post_id)
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == (
        "X didn't confirm part 1. It may have been published. Check your X profile."
    )
    assert [p["live"] for p in failed["parts"]] == [False, False]
    assert len(fake_x_publisher.published) == 1


async def test_an_upload_outlasting_its_limit_retries_like_one_x_didnt_take(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
    monkeypatch,
):
    monkeypatch.setattr(publish_module, "UPLOAD_LIMIT", timedelta(milliseconds=10))
    await connect_x()
    post_id = await post_with("A picture")
    await _attach(client, post_id, png())
    await _due(client, post_id, fixed_clock)

    async def stall() -> None:
        await asyncio.sleep(1)

    fake_x_publisher.while_uploading = stall

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "scheduled"
    assert fake_x_publisher.published == []


async def test_a_stored_file_that_cant_be_read_fails_the_post_with_nothing_published(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
    monkeypatch,
):
    await connect_x()
    post_id = await post_with("One", "Two")
    await _attach(client, post_id, png(), part=2)
    await _due(client, post_id, fixed_clock)

    async def unreadable(key: str):
        raise OSError("disk unplugged")

    monkeypatch.setattr(file_storage, "open", unreadable)

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    failed = await _scheduled_post(client, post_id)
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == (
        "Part 2 not published: Pumpkit couldn't send its media to X. Reschedule it to try again."
    )
    assert [p["live"] for p in failed["parts"]] == [True, False]


def _taking(fixed_clock, wait: timedelta):
    """An upload during which `wait` passes."""

    async def take() -> None:
        fixed_clock.advance(wait)

    return take


async def test_a_post_published_after_a_long_upload_is_published_when_x_took_it(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("A picture")
    await _attach(client, post_id, png())
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.while_uploading = _taking(fixed_clock, timedelta(minutes=4))

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    published = await _scheduled_post(client, post_id)
    assert datetime.fromisoformat(published["published_at"]) == fixed_clock()


async def test_a_long_upload_x_didnt_take_waits_its_backoff_from_when_it_ended(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("A picture")
    await _attach(client, post_id, png())
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.while_uploading = _taking(fixed_clock, timedelta(minutes=5))
    fake_x_publisher.fail_upload = XRateLimitedError("429")
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    fake_x_publisher.while_uploading = None
    fake_x_publisher.fail_upload = None

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    waiting = await _scheduled_post(client, post_id)
    assert waiting["state"] == "scheduled", waiting["failed_reason"]
    assert fake_x_publisher.upload_attempts == 1

    fixed_clock.advance(timedelta(minutes=1))
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"


async def test_a_stored_file_with_an_invalid_key_fails_the_post_with_nothing_published(
    client,
    db,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("A picture")
    media = await _attach(client, post_id, png())
    await _due(client, post_id, fixed_clock)
    await db.execute(update(Media).where(Media.id == media["id"]).values(file_key="../escape"))
    await db.commit()

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    failed = await _scheduled_post(client, post_id)
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == (
        "Not published: Pumpkit couldn't send its media to X. Reschedule it to try again."
    )
    assert fake_x_publisher.uploads == []


async def test_a_bug_while_uploading_is_not_taken_for_a_failed_upload(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("A picture")
    await _attach(client, post_id, png())
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.fail_upload = KeyError("tweet_image")

    with pytest.raises(KeyError):
        await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)


async def test_a_file_whose_key_cant_be_deleted_leaves_the_part_published(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
    monkeypatch,
):
    await connect_x()
    post_id = await post_with("A picture")
    await _attach(client, post_id, png())
    await _due(client, post_id, fixed_clock)

    async def invalid_key(key: str) -> None:
        raise ValueError(f"Not a valid storage key: {key!r}")

    monkeypatch.setattr(file_storage, "delete", invalid_key)

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"


async def _connect_x_before_media(db) -> None:
    await db.execute(
        update(XConnection).values(scopes="tweet.read tweet.write users.read offline.access")
    )
    await db.commit()


async def test_scheduling_media_on_an_x_connection_without_media_write_asks_to_reconnect(
    client, db, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("A picture")
    await _attach(client, post_id, png())
    await _connect_x_before_media(db)

    response = await _schedule(client, post_id)

    assert response.status_code == 409, response.text
    assert (
        response.json()["detail"]
        == "X no longer accepts Pumpkit's access to your account. Reconnect X first."
    )
    assert (await client.get(f"{POSTS}/{post_id}")).json()["scheduled_post"] is None


async def test_rescheduling_media_on_an_x_connection_without_media_write_asks_to_reconnect(
    client, db, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("A picture")
    await _attach(client, post_id, png())
    scheduled_post = (await _schedule(client, post_id)).json()
    await _connect_x_before_media(db)

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled_post['id']}", json={"publish_at": "2026-10-11T14:00:00Z"}
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "X_RECONNECT_FOR_MEDIA"


async def test_media_a_live_part_kept_is_refused_on_a_later_part(
    client,
    db,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
    monkeypatch,
):
    await connect_x()
    post_id = await post_with("One", "Two")
    kept = await _attach(client, post_id, png())
    scheduled_post = await _due(client, post_id, fixed_clock)
    fake_x_publisher.fail_publish = XPostRejectedError(400, "No.")
    fake_x_publisher.fail_publish_on = 2

    async def undeletable(key: str) -> None:
        raise OSError("read-only disk")

    monkeypatch.setattr(file_storage, "delete", undeletable)
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    # No request moves Media between Parts yet; feedback that drops a Part can.
    await db.execute(update(TextMedia).where(TextMedia.media_id == kept["id"]).values(part_index=1))
    await db.commit()

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled_post['id']}", json={"copy_text": True}
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "MEDIA_ON_TWO_PARTS"
    assert response.json()["detail"] == (
        "Part 2 has media that's already on an earlier part. Remove it and attach the file again."
    )
