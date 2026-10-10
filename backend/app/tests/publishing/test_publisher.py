"""
The publisher's single pass, called directly with the fake X publisher and the frozen clock.
Scheduled posts are made and checked through the HTTP API.
"""

import asyncio
from datetime import timedelta
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient

import app.api.services.scheduled_posts as scheduled_posts_service
import app.publishing.publish as publish_module
import app.publishing.publisher as publisher_module
from app.core.x_publisher import (
    XNotReceivedError,
    XOutcomeUnknownError,
    XRateLimitedError,
)
from app.publishing.publisher import run, run_pass

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
CHECK_X_REASON = "X didn't confirm this post. It may have been published, check your X profile."
X_UNAVAILABLE_REASON = "Not published: X was busy or unreachable. Try again in a few minutes."


async def _connect_x(client: AsyncClient) -> None:
    started = await client.post("/api/v1/x-connection/authorizations")
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
    completed = await client.post(
        "/api/v1/x-connection/authorizations/complete", json={"code": "c", "state": state}
    )
    assert completed.status_code == 200, completed.text


async def _schedule(client: AsyncClient, publish_at: str, text: str = "Later today.") -> str:
    response = await client.post(SCHEDULED_POSTS, json={"text": text, "publish_at": publish_at})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _listed(client: AsyncClient) -> dict[str, dict]:
    return {p["text"]: p for p in (await client.get(SCHEDULED_POSTS)).json()["data"]}


async def test_a_scheduled_post_is_published_once_due_and_never_before(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    await _schedule(client, "2026-10-10T12:05:00Z", "At five past")
    fixed_clock.advance(timedelta(minutes=4, seconds=29))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert (await _listed(client))["At five past"]["state"] == "scheduled"
    assert fake_x_publisher.published == []

    fixed_clock.advance(timedelta(seconds=1))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    published = (await _listed(client))["At five past"]
    assert published["state"] == "published"
    assert published["published_at"] == "2026-10-10T12:05:00Z"
    assert published["x_post_url"] == "https://x.com/i/web/status/1890000000000000001"
    assert fake_x_publisher.published == [("access-1001-1", "At five past")]


async def test_one_pass_publishes_every_due_scheduled_post(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    await _schedule(client, "2026-10-10T12:03:00Z", "First")
    await _schedule(client, "2026-10-10T12:02:00Z", "Second")
    await _schedule(client, "2026-10-10T13:00:00Z", "Later")
    fixed_clock.advance(timedelta(minutes=5))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert [text for _, text in fake_x_publisher.published] == ["Second", "First"]
    assert (await _listed(client))["Later"]["state"] == "scheduled"


async def test_two_passes_at_once_publish_each_scheduled_post_once(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    for minute in (2, 3, 4):
        await _schedule(client, f"2026-10-10T12:0{minute}:00Z", f"Post {minute}")
    fixed_clock.advance(timedelta(minutes=5))
    # The first call to X waits until another one starts, so both passes are mid-publish.
    another_started = asyncio.Event()
    publish = fake_x_publisher.publish

    async def overlapping_publish(*, access_token: str, text: str) -> str:
        if fake_x_publisher.published:
            another_started.set()
            return await publish(access_token=access_token, text=text)
        posted = await publish(access_token=access_token, text=text)
        await asyncio.wait_for(another_started.wait(), timeout=5)
        return posted

    fake_x_publisher.publish = overlapping_publish

    await asyncio.gather(
        run_pass(db_session_maker, fake_x_publisher, fixed_clock),
        run_pass(db_session_maker, fake_x_publisher, fixed_clock),
    )

    assert sorted(text for _, text in fake_x_publisher.published) == ["Post 2", "Post 3", "Post 4"]
    assert {p["state"] for p in (await _listed(client)).values()} == {"published"}


@pytest.mark.parametrize("error", [XRateLimitedError("429"), XNotReceivedError("ConnectError")])
async def test_a_post_x_never_took_is_retried_after_a_backoff(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, error
):
    await _connect_x(client)
    await _schedule(client, "2026-10-10T12:02:00Z", "Busy X")
    fixed_clock.advance(timedelta(minutes=1, seconds=30))
    fake_x_publisher.fail_publish = error

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    waiting = (await _listed(client))["Busy X"]
    assert waiting["state"] == "scheduled"
    assert waiting["failed_reason"] is None

    fake_x_publisher.fail_publish = None
    fixed_clock.advance(timedelta(seconds=30))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert len(fake_x_publisher.published) == 1

    fixed_clock.advance(timedelta(seconds=30))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert (await _listed(client))["Busy X"]["state"] == "published"
    assert len(fake_x_publisher.published) == 2


async def test_a_refresh_x_never_took_is_retried_too(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    await _schedule(client, "2026-10-10T14:00:00Z", "Needs a fresh token")
    fixed_clock.advance(timedelta(hours=2))
    fake_x_publisher.fail_refresh = XNotReceivedError("ConnectError")

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert (await _listed(client))["Needs a fresh token"]["state"] == "scheduled"
    fake_x_publisher.fail_refresh = None
    fixed_clock.advance(timedelta(minutes=1))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    assert (await _listed(client))["Needs a fresh token"]["state"] == "published"


async def test_a_rate_limited_post_gives_up_as_failed_15_minutes_after_its_publish_time(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    await _schedule(client, "2026-10-10T12:02:00Z", "Never goes out")
    fixed_clock.advance(timedelta(minutes=1, seconds=30))
    fake_x_publisher.fail_publish = XRateLimitedError("429")

    # Every 30 seconds, like the publisher, up to a minute before giving up.
    for _ in range(28):
        await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
        fixed_clock.advance(timedelta(seconds=30))
    assert (await _listed(client))["Never goes out"]["state"] == "scheduled"
    tries_before_the_deadline = len(fake_x_publisher.published)

    for _ in range(4):
        await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
        fixed_clock.advance(timedelta(seconds=30))

    failed = (await _listed(client))["Never goes out"]
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == X_UNAVAILABLE_REASON
    # Backed off: far fewer calls than passes, and one last try at the deadline.
    assert 3 <= tries_before_the_deadline <= 6
    assert len(fake_x_publisher.published) == tries_before_the_deadline + 1


async def test_a_post_whose_outcome_is_unknown_fails_without_a_retry(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    await _schedule(client, "2026-10-10T12:02:00Z", "Timed out")
    fixed_clock.advance(timedelta(minutes=2))
    fake_x_publisher.fail_publish = XOutcomeUnknownError("timeout")

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    fixed_clock.advance(timedelta(minutes=5))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    failed = (await _listed(client))["Timed out"]
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == CHECK_X_REASON
    assert len(fake_x_publisher.published) == 1


async def _crashed_mid_publish(db_session_maker, scheduled_post_id: str, clock) -> None:
    """Claimed into publishing by a publisher that died before recording the outcome."""
    async with db_session_maker() as session:
        assert await scheduled_posts_service.claim(
            session, scheduled_post_id=scheduled_post_id, now=clock()
        )
        await session.commit()


async def test_a_post_stuck_in_publishing_for_over_10_minutes_becomes_failed(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, monkeypatch
):
    captured = MagicMock()
    monkeypatch.setattr(publisher_module, "posthog_client", captured)
    await _connect_x(client)
    scheduled_post_id = await _schedule(client, "2026-10-10T12:02:00Z", "Stuck")
    fixed_clock.advance(timedelta(minutes=2))
    await _crashed_mid_publish(db_session_maker, scheduled_post_id, fixed_clock)
    fixed_clock.advance(timedelta(minutes=10))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert (await _listed(client))["Stuck"]["state"] == "publishing"

    fixed_clock.advance(timedelta(seconds=30))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    stuck = (await _listed(client))["Stuck"]
    assert stuck["state"] == "failed"
    assert stuck["failed_reason"] == CHECK_X_REASON
    assert fake_x_publisher.published == []
    captured.capture.assert_called_once_with(
        "scheduled_post_failed",
        distinct_id=subscribed.user_id,
        properties={"reason": "outcome_unknown"},
    )


async def test_the_loop_runs_passes_until_it_is_stopped(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    await _schedule(client, "2026-10-10T12:02:00Z", "From the loop")
    fixed_clock.advance(timedelta(minutes=2))
    stop = asyncio.Event()

    looping = asyncio.create_task(
        run(
            db_session_maker,
            fake_x_publisher,
            fixed_clock,
            poll_interval=timedelta(milliseconds=10),
            stop=stop,
        )
    )
    await asyncio.sleep(0.2)
    stop.set()
    await asyncio.wait_for(looping, timeout=1)

    assert (await _listed(client))["From the loop"]["state"] == "published"


async def test_the_pass_tracks_what_it_publishes(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, monkeypatch
):
    captured = MagicMock()
    monkeypatch.setattr(publish_module, "posthog_client", captured)
    await _connect_x(client)
    await _schedule(client, "2026-10-10T12:02:00Z")
    fixed_clock.advance(timedelta(minutes=2))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    captured.capture.assert_called_once_with(
        "scheduled_post_published",
        distinct_id=subscribed.user_id,
        properties={"source": "typed"},
    )
