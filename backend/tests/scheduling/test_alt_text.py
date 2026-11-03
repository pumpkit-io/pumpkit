"""
Writing alt text for Media on a Post's Text, through `PUT /posts/{id}/text/media/{media_id}/alt-text`,
and on a waiting Scheduled post, through `PUT /scheduled-posts/{id}/media/{media_id}/alt-text`, and
reading it back on `GET /posts/{id}`. Only the User writes it, up to 1,000 characters, on images
and GIFs, and the publisher sets it on X after each upload, before the X post that carries it.
"""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from pumpkit.posts.models import Media
from pumpkit.scheduling.models import PUBLISHED, PUBLISHING, ScheduledPost
from pumpkit.scheduling.publisher import run_pass
from pumpkit.scheduling.publishing import recover_stuck
from pumpkit.x_connection.x_publisher import (
    FakeAltText,
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


async def _attach(client: AsyncClient, post_id: str, *, part: int = 1) -> dict:
    response = await client.post(
        f"{POSTS}/{post_id}/text/parts/{part}/media",
        files={"file": ("photo.png", png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _describe(client: AsyncClient, post_id: str, media_id: str, alt_text):
    return await client.put(
        f"{POSTS}/{post_id}/text/media/{media_id}/alt-text", json={"alt_text": alt_text}
    )


async def _describe_on_scheduled_post(
    client: AsyncClient, scheduled_post_id: str, media_id: str, alt_text
):
    return await client.put(
        f"{SCHEDULED_POSTS}/{scheduled_post_id}/media/{media_id}/alt-text",
        json={"alt_text": alt_text},
    )


async def _read(client: AsyncClient, post_id: str) -> dict:
    response = await client.get(f"{POSTS}/{post_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _alt_texts(parts: list[dict]) -> list[list]:
    return [[m["alt_text"] for m in part["media"]] for part in parts]


async def test_alt_text_written_on_the_texts_image_is_read_back(client, subscribed, post_with):
    post_id = await post_with("One", "Two")
    first = await _attach(client, post_id)
    second = await _attach(client, post_id, part=2)

    response = await _describe(client, post_id, second["id"], "Gulls over the harbour at dawn.")

    assert response.status_code == 200, response.text
    assert response.json() == {**second, "alt_text": "Gulls over the harbour at dawn."}
    read = await _read(client, post_id)
    assert _alt_texts(read["text"]["parts"]) == [[None], ["Gulls over the harbour at dawn."]]
    assert read["text"]["parts"][0]["media"] == [first]


async def test_alt_text_is_stripped_and_cleared_when_empty_or_null(client, subscribed, post_with):
    post_id = await post_with("One")
    media = await _attach(client, post_id)

    stripped = await _describe(client, post_id, media["id"], f"  {'a' * 1000}\n")
    emptied = await _describe(client, post_id, media["id"], "   ")
    await _describe(client, post_id, media["id"], "Again.")
    nulled = await _describe(client, post_id, media["id"], None)

    assert stripped.json()["alt_text"] == "a" * 1000
    assert emptied.json()["alt_text"] is None
    assert nulled.status_code == 200, nulled.text
    assert _alt_texts((await _read(client, post_id))["text"]["parts"]) == [[None]]


async def test_alt_text_past_1000_characters_is_refused(client, subscribed, post_with):
    post_id = await post_with("One")
    media = await _attach(client, post_id)

    response = await _describe(client, post_id, media["id"], "a" * 1001)

    assert response.status_code == 422, response.text
    assert "Alt text can be up to 1,000 characters." in response.text
    assert _alt_texts((await _read(client, post_id))["text"]["parts"]) == [[None]]


async def test_a_video_takes_no_alt_text(client, db, subscribed, post_with):
    post_id = await post_with("One")
    media = await _attach(client, post_id)
    await db.execute(update(Media).where(Media.id == media["id"]).values(kind="video"))
    await db.commit()

    response = await _describe(client, post_id, media["id"], "A clip.")

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "MEDIA_ALT_TEXT_UNSUPPORTED"
    assert response.json()["detail"] == "Alt text is for images and GIFs."


async def test_media_the_text_does_not_hold_is_not_found(
    client, subscribed, post_with, sign_in_as_another_subscribed_user
):
    post_id = await post_with("One")
    media = await _attach(client, post_id)

    unknown = await _describe(client, post_id, "media_nope", "Hi.")
    await sign_in_as_another_subscribed_user()
    not_mine = await _describe(client, post_id, media["id"], "Hi.")

    assert unknown.status_code == 404, unknown.text
    assert not_mine.status_code == 404, not_mine.text


async def test_a_scheduled_posts_text_takes_no_alt_text_but_its_scheduled_post_does(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One", "Two")
    media = await _attach(client, post_id, part=2)
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})
    assert scheduled.status_code == 201, scheduled.text

    on_text = await _describe(client, post_id, media["id"], "On the text.")
    on_scheduled_post = await _describe_on_scheduled_post(
        client, scheduled.json()["id"], media["id"], "A bar chart of signups."
    )

    assert on_text.status_code == 409, on_text.text
    assert on_scheduled_post.status_code == 200, on_scheduled_post.text
    assert on_scheduled_post.json()["alt_text"] == "A bar chart of signups."
    read = await _read(client, post_id)
    assert _alt_texts(read["scheduled_post"]["parts"]) == [[], ["A bar chart of signups."]]


async def test_alt_text_written_on_the_text_is_copied_onto_the_scheduled_post(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One")
    media = await _attach(client, post_id)
    await _describe(client, post_id, media["id"], "A rising line.")

    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})

    assert _alt_texts(scheduled.json()["parts"]) == [["A rising line."]]


async def test_media_the_scheduled_post_does_not_hold_is_not_found(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One")
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})

    response = await _describe_on_scheduled_post(client, scheduled.json()["id"], "media_x", "Hi.")

    assert response.status_code == 404, response.text


async def test_a_part_already_on_x_keeps_its_alt_text(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Live one.", "Refused two.")
    live = await _attach(client, post_id, part=1)
    waiting = await _attach(client, post_id, part=2)
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = 2
    failed = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert failed.json()["state"] == "failed", failed.text

    on_text = await _describe(client, post_id, live["id"], "Too late.")
    on_refused_part = await _describe(client, post_id, waiting["id"], "In time.")

    assert on_text.status_code == 409, on_text.text
    assert on_text.json()["detail"] == "Part 1 is already on X, so its media is set."
    assert on_refused_part.status_code == 200, on_refused_part.text


async def test_a_waiting_scheduled_posts_part_already_on_x_keeps_its_alt_text(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Live one.", "Waiting two.")
    live = await _attach(client, post_id, part=1)
    waiting = await _attach(client, post_id, part=2)
    fake_x_publisher.fail_publish = XRateLimitedError("429")
    fake_x_publisher.fail_publish_on = 2
    retrying = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert retrying.json()["state"] == "scheduled", retrying.text

    on_live_part = await _describe_on_scheduled_post(
        client, retrying.json()["id"], live["id"], "Too late."
    )
    on_waiting_part = await _describe_on_scheduled_post(
        client, retrying.json()["id"], waiting["id"], "In time."
    )

    assert on_live_part.status_code == 409, on_live_part.text
    assert on_waiting_part.status_code == 200, on_waiting_part.text


async def test_a_failed_scheduled_post_takes_alt_text_only_through_the_text(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Refused.")
    media = await _attach(client, post_id)
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    failed = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert failed.json()["state"] == "failed", failed.text

    response = await _describe_on_scheduled_post(
        client, failed.json()["id"], media["id"], "Not here."
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        "This scheduled post failed, so its alt text changes on the post's text."
    )
    assert _alt_texts((await _read(client, post_id))["text"]["parts"]) == [[None]]


@pytest.mark.parametrize("state", [PUBLISHING, PUBLISHED])
async def test_a_scheduled_post_publishing_or_published_takes_no_alt_text(
    state, client, db, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Going out.")
    media = await _attach(client, post_id)
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})
    assert scheduled.status_code == 201, scheduled.text
    await db.execute(
        update(ScheduledPost).where(ScheduledPost.id == scheduled.json()["id"]).values(state=state)
    )
    await db.commit()

    response = await _describe_on_scheduled_post(
        client, scheduled.json()["id"], media["id"], "Too late."
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        "Publishing has started, so this scheduled post can no longer change."
    )
    assert _alt_texts((await _read(client, post_id))["text"]["parts"]) == [[None]]


async def _due(client: AsyncClient, post_id: str, fixed_clock) -> dict:
    response = await client.post(
        SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": "2026-10-10T12:05:00Z"}
    )
    assert response.status_code == 201, response.text
    fixed_clock.advance(timedelta(minutes=5))
    return response.json()


async def _scheduled_post(client: AsyncClient, post_id: str) -> dict:
    return (await _read(client, post_id))["scheduled_post"]


async def test_the_publisher_sets_alt_text_on_x_after_the_upload_and_before_the_x_post(
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
    described = await _attach(client, post_id)
    await _attach(client, post_id)
    await _attach(client, post_id, part=2)
    await _describe(client, post_id, described["id"], "Gulls over the harbour.")
    await _due(client, post_id, fixed_clock)
    alt_texts_at_each_post: list[list] = []

    async def note_alt_texts() -> None:
        alt_texts_at_each_post.append(list(fake_x_publisher.alt_texts))

    fake_x_publisher.while_publishing = note_alt_texts

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"
    first_upload = fake_x_publisher.uploads[0]
    sent = [FakeAltText("access-1001-1", first_upload.media_id, "Gulls over the harbour.")]
    assert fake_x_publisher.alt_texts == sent
    assert alt_texts_at_each_post == [sent, sent]


async def test_media_without_alt_text_sends_none_to_x(
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
    post_id = await post_with("One")
    await _attach(client, post_id)
    await _due(client, post_id, fixed_clock)

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"
    assert fake_x_publisher.alt_texts == []


async def test_a_video_holding_alt_text_sends_none_to_x(
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
    post_id = await post_with("One")
    media = await _attach(client, post_id)
    # No request stores alt text on a video; a record written before that rule could hold one.
    await db.execute(
        update(Media).where(Media.id == media["id"]).values(kind="video", alt_text="A clip.")
    )
    await db.commit()
    await _due(client, post_id, fixed_clock)

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"
    assert fake_x_publisher.alt_texts == []


async def _due_with_alt_text(client, post_id: str, fixed_clock, *, part: int = 1) -> None:
    media = await _attach(client, post_id, part=part)
    await _describe(client, post_id, media["id"], "A rising line.")
    await _due(client, post_id, fixed_clock)


@pytest.mark.parametrize(
    "error",
    [
        XRateLimitedError("429"),
        XMediaUnavailableError("X answered HTTP 503 setting alt text"),
        XNotReceivedError("refused connection"),
    ],
)
async def test_alt_text_x_didnt_take_retries_in_the_window_with_nothing_published(
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
    await _due_with_alt_text(client, post_id, fixed_clock)
    fake_x_publisher.fail_alt_text = error

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "scheduled"
    assert fake_x_publisher.published == []

    fake_x_publisher.fail_alt_text = None
    fixed_clock.advance(timedelta(minutes=1))
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"
    assert [a.text for a in fake_x_publisher.alt_texts] == ["A rising line."]


async def test_alt_text_x_refuses_fails_the_post_with_xs_reason_naming_the_part(
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
    await _due_with_alt_text(client, post_id, fixed_clock, part=2)
    fake_x_publisher.fail_alt_text = XMediaRefusedError(400, "Invalid alt text.")

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    failed = await _scheduled_post(client, post_id)
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == (
        "X refused the alt text of the media on part 2: Invalid alt text."
    )
    assert [p["live"] for p in failed["parts"]] == [True, False]
    assert len(fake_x_publisher.published) == 1


async def test_alt_text_x_refuses_the_token_for_needs_a_reconnect(
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
    await _due_with_alt_text(client, post_id, fixed_clock)
    fake_x_publisher.fail_alt_text = XReconnectNeededError("401")

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    failed = await _scheduled_post(client, post_id)
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == RECONNECT_REASON
    assert fake_x_publisher.published == []
    assert (await client.get("/api/v1/x-connection")).json()["needs_reconnect"] is True


async def test_a_publish_renews_its_claim_before_setting_alt_text_so_recovery_leaves_it_be(
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
    await _due_with_alt_text(client, post_id, fixed_clock)

    async def recover_after_six_minutes() -> None:
        fixed_clock.advance(timedelta(minutes=6))
        async with db_session_maker() as session:
            await recover_stuck(session, now=fixed_clock())

    fake_x_publisher.while_uploading = recover_after_six_minutes
    fake_x_publisher.while_setting_alt_text = recover_after_six_minutes

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    published = await _scheduled_post(client, post_id)
    assert published["state"] == "published"
    assert published["failed_reason"] is None
