"""
The publisher's single pass, called directly with the fake X publisher and the frozen clock.
Scheduled posts are made and checked through the HTTP API.
"""

import asyncio
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

import pumpkit.scheduling.publish as publish_module
import pumpkit.scheduling.service as scheduled_posts_service
from pumpkit.scheduling.publisher import HEARTBEAT_FILE, run, run_pass
from pumpkit.x_connection.x_publisher import (
    XNotReceivedError,
    XOutcomeUnknownError,
    XPostRejectedError,
    XRateLimitedError,
)

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
CHECK_X_REASON = "X didn't confirm this post. It may have been published. Check your X profile."
X_UNAVAILABLE_REASON = "Not published: X was busy or unreachable. Try again in a few minutes."


async def _schedule(
    client: AsyncClient, version_of, publish_at: str, text: str = "Later today."
) -> str:
    response = await client.post(
        SCHEDULED_POSTS,
        json={"source_version_id": await version_of(text), "publish_at": publish_at},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _listed(client: AsyncClient) -> dict[str, dict]:
    return {p["parts"][0]["text"]: p for p in (await client.get(SCHEDULED_POSTS)).json()["data"]}


async def test_a_scheduled_post_is_published_once_due_and_never_before(
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    await _schedule(client, version_of, "2026-10-10T12:05:00Z", "At five past")
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


async def _schedule_thread(
    client: AsyncClient, version_of, publish_at: str, parts: list[str]
) -> str:
    response = await client.post(
        SCHEDULED_POSTS,
        json={"source_version_id": await version_of(*parts), "publish_at": publish_at},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_a_due_thread_goes_out_as_a_chain_each_part_replying_to_the_one_before(
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    await _schedule_thread(
        client, version_of, "2026-10-10T12:05:00Z", ["Part one", "Part two", "Part three"]
    )
    fixed_clock.advance(timedelta(minutes=5))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert [text for _, text in fake_x_publisher.published] == [
        "Part one",
        "Part two",
        "Part three",
    ]
    assert fake_x_publisher.replied_to == [
        None,
        "1890000000000000001",
        "1890000000000000002",
    ]
    published = (await _listed(client))["Part one"]
    assert published["state"] == "published"
    assert published["x_post_url"] == "https://x.com/i/web/status/1890000000000000001"
    assert [(p["live"], p["x_post_url"]) for p in published["parts"]] == [
        (True, "https://x.com/i/web/status/1890000000000000001"),
        (True, "https://x.com/i/web/status/1890000000000000002"),
        (True, "https://x.com/i/web/status/1890000000000000003"),
    ]


async def test_a_thread_x_rate_limits_partway_goes_on_from_that_part_after_a_backoff(
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    await _schedule_thread(client, version_of, "2026-10-10T12:02:00Z", ["One", "Two", "Three"])
    fixed_clock.advance(timedelta(minutes=2))
    fake_x_publisher.fail_publish = XRateLimitedError("429")
    fake_x_publisher.fail_publish_on = 2

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    waiting = (await _listed(client))["One"]
    assert waiting["state"] == "scheduled"
    assert [p["live"] for p in waiting["parts"]] == [True, False, False]

    fixed_clock.advance(timedelta(minutes=1))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert [text for _, text in fake_x_publisher.published] == ["One", "Two", "Two", "Three"]
    assert fake_x_publisher.replied_to == [
        None,
        "1890000000000000001",
        "1890000000000000001",
        "1890000000000000003",
    ]
    published = (await _listed(client))["One"]
    assert published["state"] == "published"
    # The time of the pass that got the last Part out.
    assert published["published_at"] == "2026-10-10T12:03:30Z"
    assert published["x_post_url"] == "https://x.com/i/web/status/1890000000000000001"


async def test_a_thread_is_not_published_while_a_part_is_not_live(
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    await _schedule_thread(client, version_of, "2026-10-10T12:02:00Z", ["First", "Second"])
    fixed_clock.advance(timedelta(minutes=2))
    fake_x_publisher.fail_publish = XOutcomeUnknownError("timeout")
    fake_x_publisher.fail_publish_on = 2

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    failed = (await _listed(client))["First"]
    assert failed["state"] == "failed"
    assert failed["published_at"] is None
    assert failed["x_post_url"] is None
    assert [p["live"] for p in failed["parts"]] == [True, False]
    assert len(fake_x_publisher.published) == 2


async def test_a_thread_whose_part_3_of_5_x_refuses_fails_keeping_parts_1_and_2_live(
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    await _schedule_thread(client, version_of, "2026-10-10T12:02:00Z", ["A", "B", "C", "D", "E"])
    fixed_clock.advance(timedelta(minutes=2))
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Duplicate content.")
    fake_x_publisher.fail_publish_on = 3

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    failed = (await _listed(client))["A"]
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == "X refused Part 3: Duplicate content."
    assert [(p["live"], p["x_post_url"]) for p in failed["parts"]] == [
        (True, "https://x.com/i/web/status/1890000000000000001"),
        (True, "https://x.com/i/web/status/1890000000000000002"),
        (False, None),
        (False, None),
        (False, None),
    ]
    assert len(fake_x_publisher.published) == 3


async def test_a_thread_whose_part_3_has_an_unknown_outcome_fails_saying_to_check_the_profile(
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    await _schedule_thread(client, version_of, "2026-10-10T12:02:00Z", ["A", "B", "C", "D", "E"])
    fixed_clock.advance(timedelta(minutes=2))
    fake_x_publisher.fail_publish = XOutcomeUnknownError("timeout")
    fake_x_publisher.fail_publish_on = 3

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    fixed_clock.advance(timedelta(minutes=5))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    failed = (await _listed(client))["A"]
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == (
        "X didn't confirm Part 3. It may have been published. Check your X profile."
    )
    assert [p["live"] for p in failed["parts"]] == [True, True, False, False, False]
    assert len(fake_x_publisher.published) == 3


async def test_a_due_community_post_goes_out_in_its_community(
    version_of,
    client,
    db_session_maker,
    subscribed,
    fake_x_publisher,
    fake_x_reader,
    fixed_clock,
    connect_x,
):
    fake_x_reader.communities["1493446837214187523"] = "Indie makers"
    await connect_x()
    response = await client.post(
        SCHEDULED_POSTS,
        json={
            "source_version_id": await version_of("For the Community"),
            "publish_at": "2026-10-10T12:05:00Z",
            "community": "1493446837214187523",
            "share_with_followers": True,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["community"] == {
        "id": "1493446837214187523",
        "name": "Indie makers",
        "url": "https://x.com/i/communities/1493446837214187523",
    }
    fixed_clock.advance(timedelta(minutes=5))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert (await _listed(client))["For the Community"]["state"] == "published"
    assert fake_x_publisher.published == [("access-1001-1", "For the Community")]
    assert fake_x_publisher.published_to == [("1493446837214187523", True)]


async def test_a_due_community_post_x_refuses_for_a_non_member_fails_with_a_membership_hint(
    version_of,
    client,
    db_session_maker,
    subscribed,
    fake_x_publisher,
    fake_x_reader,
    fixed_clock,
    connect_x,
):
    fake_x_reader.communities["1493446837214187523"] = "Indie makers"
    await connect_x()
    response = await client.post(
        SCHEDULED_POSTS,
        json={
            "source_version_id": await version_of("Not a member"),
            "publish_at": "2026-10-10T12:05:00Z",
            "community": "1493446837214187523",
        },
    )
    assert response.status_code == 201, response.text
    fake_x_publisher.fail_publish = XPostRejectedError(
        403, "You do not have permission to create this Tweet."
    )
    fixed_clock.advance(timedelta(minutes=5))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    failed = (await _listed(client))["Not a member"]
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == (
        "X refused the post: You do not have permission to create this Tweet. Check that your "
        "X account is a member of this Community and allowed to post in it."
    )


async def test_a_due_scheduled_post_publishes_without_a_subscription_where_no_plans_are_sold(
    version_of, client, db_session_maker, sells_no_plans, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    await _schedule(client, version_of, "2026-10-10T12:05:00Z", "No Plans here")
    fixed_clock.advance(timedelta(minutes=5))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert (await _listed(client))["No Plans here"]["state"] == "published"
    assert fake_x_publisher.published == [("access-1001-1", "No Plans here")]


async def test_one_pass_publishes_every_due_scheduled_post(
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    await _schedule(client, version_of, "2026-10-10T12:03:00Z", "First")
    await _schedule(client, version_of, "2026-10-10T12:02:00Z", "Second")
    await _schedule(client, version_of, "2026-10-10T13:00:00Z", "Later")
    fixed_clock.advance(timedelta(minutes=5))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert [text for _, text in fake_x_publisher.published] == ["Second", "First"]
    assert (await _listed(client))["Later"]["state"] == "scheduled"


async def test_two_passes_at_once_publish_each_scheduled_post_once(
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    for minute in (2, 3, 4):
        await _schedule(client, version_of, f"2026-10-10T12:0{minute}:00Z", f"Post {minute}")
    fixed_clock.advance(timedelta(minutes=5))
    # The first call to X waits until another one starts, so both passes are mid-publish.
    another_started = asyncio.Event()
    publish = fake_x_publisher.publish

    async def overlapping_publish(**kwargs) -> str:
        if fake_x_publisher.published:
            another_started.set()
            return await publish(**kwargs)
        posted = await publish(**kwargs)
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
    version_of,
    client,
    db_session_maker,
    subscribed,
    fake_x_publisher,
    fixed_clock,
    error,
    connect_x,
):
    await connect_x()
    await _schedule(client, version_of, "2026-10-10T12:02:00Z", "Busy X")
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
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    await _schedule(client, version_of, "2026-10-10T14:00:00Z", "Needs a fresh token")
    fixed_clock.advance(timedelta(hours=2))
    fake_x_publisher.fail_refresh = XNotReceivedError("ConnectError")

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert (await _listed(client))["Needs a fresh token"]["state"] == "scheduled"
    fake_x_publisher.fail_refresh = None
    fixed_clock.advance(timedelta(minutes=1))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    assert (await _listed(client))["Needs a fresh token"]["state"] == "published"


async def test_a_rate_limited_post_gives_up_as_failed_15_minutes_after_its_publish_time(
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    await _schedule(client, version_of, "2026-10-10T12:02:00Z", "Never goes out")
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
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    await _schedule(client, version_of, "2026-10-10T12:02:00Z", "Timed out")
    fixed_clock.advance(timedelta(minutes=2))
    fake_x_publisher.fail_publish = XOutcomeUnknownError("timeout")

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    fixed_clock.advance(timedelta(minutes=5))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    failed = (await _listed(client))["Timed out"]
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == CHECK_X_REASON
    assert len(fake_x_publisher.published) == 1


async def _crashed_mid_publish(
    db_session_maker, scheduled_post_id: str, clock, *, live_parts: int = 0
) -> None:
    """
    Claimed into publishing by a publisher that died before recording the outcome, after
    recording its first `live_parts` Parts as live.
    """
    async with db_session_maker() as session:
        assert await scheduled_posts_service.claim(
            session, scheduled_post_id=scheduled_post_id, now=clock()
        )
        scheduled_post = await scheduled_posts_service.get(
            session, scheduled_post_id=scheduled_post_id
        )
        assert scheduled_post is not None
        for part in scheduled_post.parts[:live_parts]:
            await scheduled_posts_service.record_part_live(
                session, part, x_post_id="1890000000000000777"
            )
        await session.commit()


async def test_a_post_stuck_in_publishing_for_over_10_minutes_becomes_failed(
    version_of,
    client,
    db_session_maker,
    subscribed,
    fake_x_publisher,
    fixed_clock,
    monkeypatch,
    connect_x,
):
    captured = MagicMock()
    monkeypatch.setattr(publish_module, "posthog_client", captured)
    await connect_x()
    scheduled_post_id = await _schedule(client, version_of, "2026-10-10T12:02:00Z", "Stuck")
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
        properties={"reason": "outcome_unknown", "format": "post", "part_count": 1},
    )


async def test_a_thread_stuck_in_publishing_after_part_1_fails_keeping_part_1_live(
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    scheduled_post_id = await _schedule_thread(
        client, version_of, "2026-10-10T12:02:00Z", ["Went out", "Unknown", "Never sent"]
    )
    fixed_clock.advance(timedelta(minutes=2))
    await _crashed_mid_publish(db_session_maker, scheduled_post_id, fixed_clock, live_parts=1)
    fixed_clock.advance(timedelta(minutes=10, seconds=30))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    stuck = (await _listed(client))["Went out"]
    assert stuck["state"] == "failed"
    assert stuck["failed_reason"] == (
        "X didn't confirm Part 2. It may have been published. Check your X profile."
    )
    assert [(p["live"], p["x_post_url"]) for p in stuck["parts"]] == [
        (True, "https://x.com/i/web/status/1890000000000000777"),
        (False, None),
        (False, None),
    ]
    assert fake_x_publisher.published == []


async def test_a_post_stuck_in_publishing_with_its_part_live_becomes_published(
    version_of,
    client,
    db_session_maker,
    subscribed,
    fake_x_publisher,
    fixed_clock,
    monkeypatch,
    connect_x,
):
    captured = MagicMock()
    monkeypatch.setattr(publish_module, "posthog_client", captured)
    await connect_x()
    scheduled_post_id = await _schedule(client, version_of, "2026-10-10T12:02:00Z", "Went out")
    fixed_clock.advance(timedelta(minutes=2))
    await _crashed_mid_publish(db_session_maker, scheduled_post_id, fixed_clock, live_parts=1)
    fixed_clock.advance(timedelta(minutes=10, seconds=30))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    published = (await _listed(client))["Went out"]
    assert published["state"] == "published"
    assert published["failed_reason"] is None
    # The time of the pass that claimed it, as that pass would have recorded.
    assert published["published_at"] == "2026-10-10T12:02:30Z"
    assert published["x_post_url"] == "https://x.com/i/web/status/1890000000000000777"
    assert fake_x_publisher.published == []
    captured.capture.assert_called_once_with(
        "scheduled_post_published",
        distinct_id=subscribed.user_id,
        properties={"source": "final", "destination": "profile", "format": "post", "part_count": 1},
    )


async def test_a_thread_stuck_in_publishing_with_every_part_live_becomes_published(
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    scheduled_post_id = await _schedule_thread(
        client, version_of, "2026-10-10T12:02:00Z", ["All out", "Also out"]
    )
    fixed_clock.advance(timedelta(minutes=2))
    await _crashed_mid_publish(db_session_maker, scheduled_post_id, fixed_clock, live_parts=2)
    fixed_clock.advance(timedelta(minutes=10, seconds=30))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    published = (await _listed(client))["All out"]
    assert published["state"] == "published"
    assert published["failed_reason"] is None
    assert published["published_at"] == "2026-10-10T12:02:30Z"
    assert [p["live"] for p in published["parts"]] == [True, True]
    assert fake_x_publisher.published == []


async def test_the_loop_runs_passes_until_it_is_stopped(
    version_of, client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    await _schedule(client, version_of, "2026-10-10T12:02:00Z", "From the loop")
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


async def test_the_loop_touches_its_heartbeat_after_each_pass_that_completes(
    db_session_maker, fake_x_publisher, fixed_clock, tmp_path
):
    heartbeat = tmp_path / "heartbeat"
    stop = asyncio.Event()

    looping = asyncio.create_task(
        run(
            db_session_maker,
            fake_x_publisher,
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


async def test_a_failing_pass_leaves_the_heartbeat_alone(fake_x_publisher, fixed_clock, tmp_path):
    heartbeat = tmp_path / "heartbeat"
    broken_session_maker = MagicMock(side_effect=RuntimeError("database unreachable"))
    stop = asyncio.Event()

    looping = asyncio.create_task(
        run(
            broken_session_maker,
            fake_x_publisher,
            fixed_clock,
            poll_interval=timedelta(milliseconds=10),
            stop=stop,
            heartbeat=heartbeat,
        )
    )
    await asyncio.sleep(0.1)
    stop.set()
    await asyncio.wait_for(looping, timeout=1)

    assert not heartbeat.exists()


def test_the_compose_healthcheck_reads_the_heartbeat_the_publisher_touches():
    compose = (Path(__file__).parents[3] / "compose.yml").read_text()

    assert f"find {HEARTBEAT_FILE} -mmin" in compose


async def test_the_pass_tracks_what_it_publishes(
    version_of,
    client,
    db_session_maker,
    subscribed,
    fake_x_publisher,
    fixed_clock,
    monkeypatch,
    connect_x,
):
    captured = MagicMock()
    monkeypatch.setattr(publish_module, "posthog_client", captured)
    await connect_x()
    await _schedule_thread(client, version_of, "2026-10-10T12:02:00Z", ["One", "Two"])
    fixed_clock.advance(timedelta(minutes=2))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    captured.capture.assert_called_once_with(
        "scheduled_post_published",
        distinct_id=subscribed.user_id,
        properties={
            "source": "final",
            "destination": "profile",
            "format": "thread",
            "part_count": 2,
        },
    )


def test_the_publisher_process_maps_every_model_it_queries():
    # A fresh interpreter, as `python -m` starts it: this test process has already imported every model.
    script = "import pumpkit.scheduling.publisher\nfrom sqlalchemy.orm import configure_mappers\nconfigure_mappers()"

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
