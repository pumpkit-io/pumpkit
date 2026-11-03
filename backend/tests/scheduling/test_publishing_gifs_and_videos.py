"""
Publishing a GIF or a video (ADR 0021): uploaded to X in chunks with its own media category and
waited on while X processes it. A video's upload can outlast the stuck threshold and the access
token's life, so the publish keeps its claim and a fresh token through every call to X.
Post now hands a GIF or a video to the publisher, due now, and every reading of the Scheduled post
says `posting` until it is Published or Failed.
"""

import asyncio
from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select

import pumpkit.scheduling.publish as publish_module
import pumpkit.x_connection.service as x_connections_service
from pumpkit.scheduling.publisher import run, run_pass
from pumpkit.scheduling.publishing import claim_next_due, publish_claimed, recover_stuck
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_publisher import (
    XMediaRefusedError,
    XPostRejectedError,
    XRateLimitedError,
)
from tests.media_files import animated_gif, mp4, png

POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
USAGE = "/api/v1/usage"


async def _attach(
    client: AsyncClient, post_id: str, data: bytes, name: str, *, part: int = 1
) -> dict:
    response = await client.post(
        f"{POSTS}/{post_id}/text/parts/{part}/media", files={"file": (name, data, "")}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _due(client: AsyncClient, post_id: str, fixed_clock) -> None:
    response = await client.post(
        SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": "2026-10-10T12:05:00Z"}
    )
    assert response.status_code == 201, response.text
    fixed_clock.advance(timedelta(minutes=5))


async def _scheduled_post(client: AsyncClient, post_id: str) -> dict:
    return (await client.get(f"{POSTS}/{post_id}")).json()["scheduled_post"]


async def test_a_gif_and_a_video_go_to_x_in_their_own_categories(
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
    post_id = await post_with("A loop.", "A demo.")
    gif = await _attach(client, post_id, animated_gif(), "loop.gif")
    await client.put(
        f"{POSTS}/{post_id}/text/media/{gif['id']}/alt-text", json={"alt_text": "A cat spins."}
    )
    await _attach(client, post_id, mp4(), "demo.mp4", part=2)
    await _due(client, post_id, fixed_clock)

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"
    assert [(u.content_type, u.category, u.data) for u in fake_x_publisher.uploads] == [
        ("image/gif", "tweet_gif", animated_gif()),
        ("video/mp4", "tweet_video", mp4()),
    ]
    gif_id, video_id = (u.media_id for u in fake_x_publisher.uploads)
    assert fake_x_publisher.published_media == [[gif_id], [video_id]]
    assert [(a.media_id, a.text) for a in fake_x_publisher.alt_texts] == [(gif_id, "A cat spins.")]


def _each_upload_call_takes(fake_x_publisher, db_session_maker, fixed_clock, wait: timedelta):
    """Every call of an upload lasts `wait`, while another publisher pass recovers stuck posts."""

    async def recover() -> None:
        fixed_clock.advance(wait)
        async with db_session_maker() as session:
            await recover_stuck(session, now=fixed_clock())

    fake_x_publisher.while_calling_x_to_upload = recover


async def test_a_video_upload_outlasting_the_stuck_threshold_keeps_its_claim(
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
    post_id = await post_with("A long demo.")
    await _attach(client, post_id, mp4(total=96), "demo.mp4")
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.chunk_bytes = 32
    fake_x_publisher.processing_polls = 3
    _each_upload_call_takes(fake_x_publisher, db_session_maker, fixed_clock, timedelta(minutes=6))

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    published = await _scheduled_post(client, post_id)
    assert published["state"] == "published"
    assert published["failed_reason"] is None
    # Initialize, 3 chunks, finalize and 3 STATUS polls: 48 minutes.
    assert fake_x_publisher.upload_calls == 8
    assert fake_x_publisher.uploads[0].data == mp4(total=96)


async def test_a_token_expiring_during_a_video_upload_is_refreshed_before_the_next_call(
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
    post_id = await post_with("A very long demo.")
    await _attach(client, post_id, mp4(total=96), "demo.mp4")
    await _due(client, post_id, fixed_clock)
    # The token from connecting has 55 minutes left; 14 calls of 6 minutes take 1 h 24.
    fixed_clock.advance(timedelta(hours=1))
    fake_x_publisher.chunk_bytes = 8
    _each_upload_call_takes(fake_x_publisher, db_session_maker, fixed_clock, timedelta(minutes=6))

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"
    assert fake_x_publisher.refreshes == ["refresh-1001-1"]
    sent = fake_x_publisher.upload_tokens
    assert (sent[0], sent[-1]) == ("access-1001-1", "access-1001-2")
    assert fake_x_publisher.published[0][0] == "access-1001-2"


async def test_a_video_upload_x_rate_limits_40_minutes_in_is_retried_after_a_backoff(
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
    post_id = await post_with("A long demo.")
    await _attach(client, post_id, mp4(total=96), "demo.mp4")
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.chunk_bytes = 8
    calls = 0

    async def slow_then_rate_limited() -> None:
        nonlocal calls
        calls += 1
        fixed_clock.advance(timedelta(minutes=5))
        if calls == 8:
            raise XRateLimitedError("429")

    fake_x_publisher.while_calling_x_to_upload = slow_then_rate_limited

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    waiting = await _scheduled_post(client, post_id)
    assert waiting["state"] == "scheduled", waiting["failed_reason"]

    fake_x_publisher.while_calling_x_to_upload = None
    fixed_clock.advance(timedelta(minutes=1))
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"


async def test_a_token_refresh_running_past_the_upload_limit_still_keeps_the_rotated_tokens(
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
    post_id = await post_with("A demo.")
    await _attach(client, post_id, mp4(), "demo.mp4")
    await _due(client, post_id, fixed_clock)
    monkeypatch.setattr(publish_module, "VIDEO_UPLOAD_LIMIT", timedelta(milliseconds=50))
    refresh = fake_x_publisher.refresh

    async def slow_refresh(**kwargs):
        tokens = await refresh(**kwargs)
        await asyncio.sleep(0.2)
        return tokens

    async def token_expires() -> None:
        fixed_clock.advance(timedelta(hours=2))
        fake_x_publisher.while_calling_x_to_upload = None

    fake_x_publisher.refresh = slow_refresh
    fake_x_publisher.while_calling_x_to_upload = token_expires

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert fake_x_publisher.refreshes == ["refresh-1001-1"]
    connection = (await db.execute(select(XConnection))).scalar_one()
    await db.refresh(connection)
    assert x_connections_service.refresh_token(connection) == "refresh-1001-2"


async def test_a_video_x_fails_to_process_fails_the_post_with_xs_reason(
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
    post_id = await post_with("A broken demo.")
    await _attach(client, post_id, mp4(), "demo.mp4")
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.fail_upload = XMediaRefusedError(None, "Unsupported video codec.")

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    failed = await _scheduled_post(client, post_id)
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == ("X refused the post's media: Unsupported video codec.")
    assert fake_x_publisher.published == []


def _upload_waits_for_another_post(fake_x_publisher, *, then_due: timedelta = timedelta(0)):
    """The upload advances the clock by `then_due`, then waits until another post is published."""
    another_published = asyncio.Event()
    publish = fake_x_publisher.publish

    async def publishing(**kwargs) -> str:
        posted = await publish(**kwargs)
        another_published.set()
        return posted

    async def waiting(fixed_clock) -> None:
        fixed_clock.advance(then_due)
        await asyncio.wait_for(another_published.wait(), timeout=5)

    fake_x_publisher.publish = publishing
    return waiting


async def _run_until_published(
    count: int, writing_session_maker, fake_x_publisher, file_storage, fixed_clock
) -> None:
    """
    The publisher's loop, stopped once `count` posts are published or after 5 seconds. Its
    publishes run side by side, so its sessions must start as writes on SQLite.
    """
    stop = asyncio.Event()
    looping = asyncio.create_task(
        run(
            writing_session_maker,
            fake_x_publisher,
            file_storage,
            fixed_clock,
            poll_interval=timedelta(milliseconds=10),
            stop=stop,
        )
    )
    for _ in range(100):
        if len(fake_x_publisher.published) == count:
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(looping, timeout=5)


async def test_a_video_upload_in_flight_doesnt_hold_up_another_due_post(
    client,
    subscribed,
    writing_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    video_post_id = await post_with("A long demo.")
    await _attach(client, video_post_id, mp4(), "demo.mp4")
    await client.post(
        SCHEDULED_POSTS, json={"post_id": video_post_id, "publish_at": "2026-10-10T12:04:00Z"}
    )
    text_post_id = await post_with("Just words.")
    await _due(client, text_post_id, fixed_clock)
    waiting = _upload_waits_for_another_post(fake_x_publisher)
    fake_x_publisher.while_uploading = lambda: waiting(fixed_clock)

    await _run_until_published(
        2, writing_session_maker, fake_x_publisher, file_storage, fixed_clock
    )

    assert [text for _, text in fake_x_publisher.published] == ["Just words.", "A long demo."]
    assert (await _scheduled_post(client, video_post_id))["state"] == "published"
    assert (await _scheduled_post(client, text_post_id))["state"] == "published"


async def test_a_post_due_while_a_video_uploads_goes_out_on_the_next_pass(
    client,
    subscribed,
    writing_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    video_post_id = await post_with("A long demo.")
    await _attach(client, video_post_id, mp4(), "demo.mp4")
    await _due(client, video_post_id, fixed_clock)
    text_post_id = await post_with("Due later.")
    await client.post(
        SCHEDULED_POSTS, json={"post_id": text_post_id, "publish_at": "2026-10-10T12:12:00Z"}
    )
    waiting = _upload_waits_for_another_post(fake_x_publisher, then_due=timedelta(minutes=7))
    fake_x_publisher.while_uploading = lambda: waiting(fixed_clock)

    await _run_until_published(
        2, writing_session_maker, fake_x_publisher, file_storage, fixed_clock
    )

    assert [text for _, text in fake_x_publisher.published] == ["Due later.", "A long demo."]


async def _run_until_stopped(
    writing_session_maker, fake_x_publisher, file_storage, fixed_clock, stop
):
    """The publisher's loop until `stop` is set; a pass's sessions run beside the publish's."""
    await asyncio.wait_for(
        run(
            writing_session_maker,
            fake_x_publisher,
            file_storage,
            fixed_clock,
            poll_interval=timedelta(milliseconds=10),
            stop=stop,
        ),
        timeout=5,
    )


async def test_a_publisher_stopped_mid_upload_hands_the_post_back_for_the_next_one(
    client,
    subscribed,
    db_session_maker,
    writing_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("A long demo.")
    await _attach(client, post_id, mp4(total=96), "demo.mp4")
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.chunk_bytes = 32
    stop = asyncio.Event()

    async def deploy_starts() -> None:
        stop.set()

    fake_x_publisher.while_calling_x_to_upload = deploy_starts

    await _run_until_stopped(
        writing_session_maker, fake_x_publisher, file_storage, fixed_clock, stop
    )

    handed_back = await _scheduled_post(client, post_id)
    assert handed_back["state"] == "scheduled"
    assert handed_back["failed_reason"] is None
    assert fake_x_publisher.upload_calls == 1
    assert fake_x_publisher.published == []

    fake_x_publisher.while_calling_x_to_upload = None
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"
    assert fake_x_publisher.uploads[0].data == mp4(total=96)


async def test_a_publisher_stopped_before_it_refreshes_the_token_calls_x_for_nothing(
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
    post_id = await post_with("A demo.")
    await _attach(client, post_id, mp4(), "demo.mp4")
    await _due(client, post_id, fixed_clock)
    fixed_clock.advance(timedelta(hours=2))
    refreshes_before = list(fake_x_publisher.refreshes)
    stop = asyncio.Event()
    async with db_session_maker() as db:
        claimed_at = fixed_clock()
        scheduled_post_id = await claim_next_due(db, now=claimed_at)
    assert scheduled_post_id is not None
    stop.set()

    async with db_session_maker() as db:
        await publish_claimed(
            db,
            fake_x_publisher,
            file_storage,
            scheduled_post_id=scheduled_post_id,
            claimed_at=claimed_at,
            clock=fixed_clock,
            stop=stop,
        )

    assert (await _scheduled_post(client, post_id))["state"] == "scheduled"
    assert fake_x_publisher.refreshes == refreshes_before
    assert fake_x_publisher.upload_calls == 0


async def test_a_publisher_stopped_while_x_takes_the_post_waits_for_its_answer(
    client,
    subscribed,
    db_session_maker,
    writing_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("A demo.")
    await _attach(client, post_id, mp4(), "demo.mp4")
    await _due(client, post_id, fixed_clock)
    stop = asyncio.Event()

    async def deploy_starts() -> None:
        stop.set()
        await asyncio.sleep(0.05)

    fake_x_publisher.while_publishing = deploy_starts

    await _run_until_stopped(
        writing_session_maker, fake_x_publisher, file_storage, fixed_clock, stop
    )

    assert (await _scheduled_post(client, post_id))["state"] == "published"
    assert [text for _, text in fake_x_publisher.published] == ["A demo."]


async def test_post_now_with_a_video_hands_it_to_the_publisher_due_now(
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
    post_id = await post_with("Right now.", "With a demo.")
    await _attach(client, post_id, mp4(), "demo.mp4", part=2)

    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})

    assert response.status_code == 201, response.text
    handed_off = response.json()
    assert (handed_off["state"], handed_off["posting"]) == ("scheduled", True)
    assert handed_off["publish_at"] == "2026-10-10T12:00:00Z"
    assert fake_x_publisher.uploads == []
    assert fake_x_publisher.published == []
    assert (await client.get(USAGE)).json()["allowance"]["x_posts"]["used"] == 2

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    published = await _scheduled_post(client, post_id)
    assert published["state"] == "published"
    assert [text for _, text in fake_x_publisher.published] == ["Right now.", "With a demo."]
    assert [u.category for u in fake_x_publisher.uploads] == ["tweet_video"]


async def test_a_handed_off_post_reads_posting_when_read_listed_and_claimed(
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
    post_id = await post_with("Right now, with a demo.")
    await _attach(client, post_id, mp4(), "demo.mp4")
    await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})

    handed_off = await _scheduled_post(client, post_id)
    [listed] = (await client.get(POSTS)).json()["data"]
    async with db_session_maker() as db:
        await claim_next_due(db, now=fixed_clock())
    claimed = await _scheduled_post(client, post_id)

    assert (handed_off["state"], handed_off["posting"]) == ("scheduled", True)
    assert listed["scheduled_post"]["posting"] is True
    assert (claimed["state"], claimed["posting"]) == ("publishing", True)


async def test_a_scheduled_post_reads_posting_once_it_is_due(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Later.")
    response = await client.post(
        SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": "2026-10-10T12:05:00Z"}
    )

    waiting = response.json()["posting"]
    fixed_clock.advance(timedelta(minutes=5))
    due = await _scheduled_post(client, post_id)

    assert waiting is False
    assert (due["state"], due["posting"]) == ("scheduled", True)


async def test_a_post_x_was_busy_for_reads_posting_again_only_when_its_retry_is_due(
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
    post_id = await post_with("A demo.")
    await _attach(client, post_id, mp4(), "demo.mp4")
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.fail_publish = XRateLimitedError("429")
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    busy = await _scheduled_post(client, post_id)
    fixed_clock.advance(timedelta(minutes=1))
    retry_due = await _scheduled_post(client, post_id)

    assert (busy["state"], busy["posting"]) == ("scheduled", False)
    assert retry_due["posting"] is True


async def test_published_and_failed_posts_read_not_posting(
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
    published_id = await post_with("Out.")
    failed_id = await post_with("Refused.")
    await _due(client, published_id, fixed_clock)
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    await client.post(
        SCHEDULED_POSTS, json={"post_id": failed_id, "publish_at": "2026-10-10T12:10:00Z"}
    )
    fixed_clock.advance(timedelta(minutes=5))
    fake_x_publisher.fail_publish = XPostRejectedError(400, "No.")
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    published = await _scheduled_post(client, published_id)
    failed = await _scheduled_post(client, failed_id)

    assert (published["state"], published["posting"]) == ("published", False)
    assert (failed["state"], failed["posting"]) == ("failed", False)


async def test_post_now_of_a_scheduled_post_with_a_video_hands_it_to_the_publisher(
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
    post_id = await post_with("Later, with a demo.")
    await _attach(client, post_id, mp4(), "demo.mp4")
    scheduled = await client.post(
        SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": "2026-10-10T14:00:00Z"}
    )

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled.json()['id']}", json={"publish_now": True}
    )

    assert response.status_code == 200, response.text
    handed_off = response.json()
    assert (handed_off["state"], handed_off["publish_at"], handed_off["posting"]) == (
        "scheduled",
        "2026-10-10T12:00:00Z",
        True,
    )
    assert fake_x_publisher.uploads == []
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    assert (await _scheduled_post(client, post_id))["state"] == "published"


async def test_post_now_with_a_gif_hands_it_to_the_publisher_too(
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
    post_id = await post_with("A loop, now.")
    await _attach(client, post_id, animated_gif(), "loop.gif")

    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})

    assert (response.json()["state"], response.json()["posting"]) == ("scheduled", True)
    assert fake_x_publisher.uploads == []
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    assert (await _scheduled_post(client, post_id))["state"] == "published"
    assert [u.category for u in fake_x_publisher.uploads] == ["tweet_gif"]


async def test_post_now_of_a_thread_whose_video_is_live_publishes_the_rest_within_the_request(
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
    post_id = await post_with("A demo.", "A chart.")
    await _attach(client, post_id, mp4(), "demo.mp4")
    await _attach(client, post_id, png(), "chart.png", part=2)
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Try again.")
    fake_x_publisher.fail_publish_on = 2
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    failed = await _scheduled_post(client, post_id)
    assert [part["live"] for part in failed["parts"]] == [True, False]
    fake_x_publisher.fail_publish = None

    retried = await client.patch(f"{SCHEDULED_POSTS}/{failed['id']}", json={"publish_now": True})

    assert retried.status_code == 200, retried.text
    assert (retried.json()["state"], retried.json()["posting"]) == ("published", False)
    assert fake_x_publisher.published[-1][1] == "A chart."
