from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

import pumpkit.scheduling.publish as publish_module
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.core.config import settings
from pumpkit.scheduling.publisher import run_pass
from pumpkit.x_connection.x_publisher import (
    XAccount,
    XNotReceivedError,
    XOutcomeUnknownError,
    XPostRejectedError,
    XRateLimitedError,
    XReconnectNeededError,
)
from tests.posts.writing_replies import written, written_thread

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
X_CONNECTION = "/api/v1/x-connection"
RECONNECT_REASON = (
    "Not published: X no longer accepts Pumpkit's access to your account. Reconnect X, then "
    "reschedule it."
)


FIRST_X_POST_URL = "https://x.com/i/web/status/1890000000000000001"


def _iso(dt) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def _post_now(client: AsyncClient, version_of, text: str = "Shipping today."):
    """Post now a new Post's one Version, whose text is `text`."""
    return await client.post(
        SCHEDULED_POSTS, json={"source_version_id": await version_of(text), "publish_now": True}
    )


def _texts(scheduled_post: dict) -> list[str]:
    return [part["text"] for part in scheduled_post["parts"]]


async def test_post_now_publishes_the_text_and_lists_it_as_published(
    client, subscribed, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()

    response = await _post_now(client, version_of, "Shipping the new onboarding today.")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "published"
    assert _texts(body) == ["Shipping the new onboarding today."]
    assert body["published_at"] == _iso(clock())
    assert body["x_post_url"] == "https://x.com/i/web/status/1890000000000000001"
    assert body["failed_reason"] is None
    assert fake_x_publisher.refreshes == []
    assert fake_x_publisher.published == [("access-1001-1", "Shipping the new onboarding today.")]
    listed = (await client.get(SCHEDULED_POSTS)).json()["data"]
    assert listed == [body]


async def test_post_now_uses_a_fresh_access_token_without_refreshing_it(
    client, subscribed, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()
    clock.advance(timedelta(hours=1, minutes=54))

    await _post_now(client, version_of)

    assert fake_x_publisher.refreshes == []
    assert fake_x_publisher.published[0][0] == "access-1001-1"


async def test_a_token_near_expiry_is_refreshed_and_the_rotated_refresh_token_kept(
    client, subscribed, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()
    clock.advance(timedelta(hours=1, minutes=56))
    first = await _post_now(client, version_of, "First")
    clock.advance(timedelta(hours=1, minutes=56))

    second = await _post_now(client, version_of, "Second")

    assert first.json()["state"] == second.json()["state"] == "published"
    assert fake_x_publisher.refreshes == ["refresh-1001-1", "refresh-1001-2"]
    assert fake_x_publisher.published == [("access-1001-2", "First"), ("access-1001-3", "Second")]


@pytest.mark.parametrize(
    ("before", "after", "char_limit"),
    [("None", "Premium", 25_000), ("PremiumPlus", "None", 280)],
)
async def test_buying_or_dropping_x_premium_changes_the_limit_at_the_next_token_refresh(
    client, subscribed, fake_x_publisher, clock, before, after, char_limit, connect_x, version_of
):
    fake_x_publisher.account = XAccount(user_id="1001", handle="ada", subscription_type=before)
    await connect_x()
    fake_x_publisher.account = XAccount(user_id="1001", handle="ada", subscription_type=after)
    clock.advance(timedelta(hours=1, minutes=56))

    await _post_now(client, version_of)

    assert (await client.get(X_CONNECTION)).json()["char_limit"] == char_limit


async def test_a_failed_subscription_type_read_keeps_the_refreshed_tokens_and_publishes(
    client, subscribed, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()
    fake_x_publisher.fail_fetch_account = XNotReceivedError("ConnectError")
    clock.advance(timedelta(hours=1, minutes=56))

    first = await _post_now(client, version_of, "First")
    clock.advance(timedelta(hours=1, minutes=56))
    second = await _post_now(client, version_of, "Second")

    assert first.json()["state"] == second.json()["state"] == "published"
    assert fake_x_publisher.refreshes == ["refresh-1001-1", "refresh-1001-2"]


async def test_post_now_without_an_x_connection_is_refused(
    client, subscribed, fake_x_publisher, clock, version_of
):
    response = await _post_now(client, version_of)

    assert response.status_code == 409
    assert response.json()["detail"] == "Connect your X account first."
    assert fake_x_publisher.published == []
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == []


async def test_a_text_over_the_limit_by_x_s_count_is_refused(
    client, subscribed, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()
    # 276 code points, but CJK characters count two each: 281 by X's count.
    text = "a" * 270 + " 日本語のテ"

    response = await _post_now(client, version_of, text)

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "This post is 281 characters by X's count, over the 280 limit."
    )
    assert fake_x_publisher.published == []


async def test_a_user_who_is_not_subscribed_cannot_post_now(
    client, fake_x_publisher, clock, version_of
):
    response = await _post_now(client, version_of)

    assert response.status_code == 403
    assert fake_x_publisher.published == []


async def test_a_user_without_a_subscription_posts_now_where_no_plans_are_sold(
    client, sells_no_plans, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()

    response = await _post_now(client, version_of)

    assert response.status_code == 201
    assert response.json()["state"] == "published"


async def test_a_post_x_refuses_fails_with_x_s_own_words(
    client, subscribed, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()
    fake_x_publisher.fail_publish = XPostRejectedError(
        403, "You are not allowed to create a Tweet with duplicate content."
    )

    response = await _post_now(client, version_of)

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "failed"
    assert body["failed_reason"] == (
        "X refused the post: You are not allowed to create a Tweet with duplicate content."
    )
    assert body["x_post_url"] is None and body["published_at"] is None
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == [body]


async def test_a_post_whose_outcome_is_unknown_fails_telling_the_user_to_check_x(
    client, subscribed, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()
    fake_x_publisher.fail_publish = XOutcomeUnknownError("X answered HTTP 503")

    response = await _post_now(client, version_of)

    assert response.json()["state"] == "failed"
    assert response.json()["failed_reason"] == (
        "X didn't confirm this post. It may have been published. Check your X profile."
    )
    assert len(fake_x_publisher.published) == 1


@pytest.mark.parametrize("error", [XRateLimitedError("429"), XNotReceivedError("ConnectError")])
async def test_a_post_now_x_never_took_goes_back_to_scheduled_for_the_publisher_to_retry(
    client, db_session_maker, subscribed, fake_x_publisher, clock, error, connect_x, version_of
):
    await connect_x()
    fake_x_publisher.fail_publish = error

    response = await _post_now(client, version_of)

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "scheduled"
    assert body["failed_reason"] is None
    fake_x_publisher.fail_publish = None
    clock.advance(timedelta(minutes=1))
    await run_pass(db_session_maker, fake_x_publisher, clock)
    [listed] = (await client.get(SCHEDULED_POSTS)).json()["data"]
    assert listed["state"] == "published"
    assert len(fake_x_publisher.published) == 2


async def test_a_post_now_x_keeps_refusing_fails_15_minutes_after_it_was_asked_for(
    client, db_session_maker, subscribed, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()
    fake_x_publisher.fail_publish = XRateLimitedError("429")
    await _post_now(client, version_of)

    for _ in range(32):
        clock.advance(timedelta(seconds=30))
        await run_pass(db_session_maker, fake_x_publisher, clock)

    [listed] = (await client.get(SCHEDULED_POSTS)).json()["data"]
    assert listed["state"] == "failed"
    assert listed["failed_reason"] == (
        "Not published: X was busy or unreachable. Try again in a few minutes."
    )


async def test_revoked_access_fails_the_post_and_asks_the_user_to_reconnect(
    client, subscribed, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()
    fake_x_publisher.fail_publish = XReconnectNeededError("401")

    response = await _post_now(client, version_of)

    assert response.json()["state"] == "failed"
    assert response.json()["failed_reason"] == RECONNECT_REASON
    assert (await client.get("/api/v1/x-connection")).json()["needs_reconnect"] is True
    fake_x_publisher.fail_publish = None
    again = await _post_now(client, version_of)
    assert again.status_code == 409
    assert again.json()["detail"] == (
        "X no longer accepts Pumpkit's access to your account. Reconnect X first."
    )
    assert len(fake_x_publisher.published) == 1


async def test_a_refresh_token_x_refuses_fails_the_post_and_asks_the_user_to_reconnect(
    client, subscribed, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()
    clock.advance(timedelta(hours=2))
    fake_x_publisher.fail_refresh = XReconnectNeededError("invalid_grant")

    response = await _post_now(client, version_of)

    assert response.json()["state"] == "failed"
    assert response.json()["failed_reason"] == RECONNECT_REASON
    assert fake_x_publisher.published == []
    assert (await client.get("/api/v1/x-connection")).json()["needs_reconnect"] is True


async def test_reconnecting_clears_the_reconnect_flag(
    client, subscribed, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()
    fake_x_publisher.fail_publish = XReconnectNeededError("401")
    await _post_now(client, version_of)
    fake_x_publisher.fail_publish = None

    await connect_x()

    assert (await client.get("/api/v1/x-connection")).json()["needs_reconnect"] is False
    assert (await _post_now(client, version_of)).json()["state"] == "published"


async def test_a_user_whose_subscription_ended_still_sees_their_scheduled_posts(
    client, db, subscribed, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()
    published = (await _post_now(client, version_of, "Went out")).json()
    clock.advance(timedelta(minutes=1))
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    failed = (await _post_now(client, version_of, "Refused")).json()
    subscribed.status = "canceled"
    await db.commit()

    response = await client.get(SCHEDULED_POSTS)

    assert response.status_code == 200
    assert response.json()["data"] == [failed, published]


async def test_published_and_failed_are_tracked_for_analytics(
    client, subscribed, fake_x_publisher, clock, monkeypatch, connect_x, version_of
):
    captured = MagicMock()
    monkeypatch.setattr(publish_module, "posthog_client", captured)
    await connect_x()
    await _post_now(client, version_of)
    fake_x_publisher.fail_publish = XOutcomeUnknownError("timeout")

    await _post_now(client, version_of)

    assert [call.args[0] for call in captured.capture.call_args_list] == [
        "scheduled_post_published",
        "scheduled_post_failed",
    ]
    published, failed = captured.capture.call_args_list
    assert published.kwargs["properties"] == {
        "source": "final",
        "destination": "profile",
        "format": "post",
        "part_count": 1,
    }
    assert failed.kwargs["properties"] == {
        "reason": "outcome_unknown",
        "format": "post",
        "part_count": 1,
    }


async def test_a_post_x_refuses_is_tracked_as_refused_by_x(
    client, subscribed, fake_x_publisher, clock, monkeypatch, connect_x, version_of
):
    captured = MagicMock()
    monkeypatch.setattr(publish_module, "posthog_client", captured)
    await connect_x()
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")

    await _post_now(client, version_of)

    captured.capture.assert_called_once_with(
        "scheduled_post_failed",
        distinct_id=subscribed.user_id,
        properties={"reason": "refused_by_x", "format": "post", "part_count": 1},
    )


async def _schedule(client: AsyncClient, version_of, publish_at: str, text: str = "Later today."):
    """Schedule a new Post's one Version, whose text is `text`, for `publish_at`."""
    return await client.post(
        SCHEDULED_POSTS,
        json={"source_version_id": await version_of(text), "publish_at": publish_at},
    )


async def test_a_post_scheduled_for_later_is_listed_as_upcoming_and_not_published(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, version_of
):
    await connect_x()

    response = await _schedule(client, version_of, "2026-10-10T14:00:00Z", "Launch day.")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "scheduled"
    assert _texts(body) == ["Launch day."]
    assert body["publish_at"] == "2026-10-10T14:00:00Z"
    assert body["published_at"] is None and body["x_post_url"] is None
    assert fake_x_publisher.published == []
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == [body]


async def test_a_publish_time_in_the_browser_s_timezone_is_stored_in_utc(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, version_of
):
    await connect_x()

    response = await _schedule(client, version_of, "2026-10-10T16:00:00+02:00")

    assert response.json()["publish_at"] == "2026-10-10T14:00:00Z"


async def test_upcoming_scheduled_posts_are_listed_soonest_first(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, version_of
):
    await connect_x()
    await _schedule(client, version_of, "2026-10-12T09:00:00Z", "Monday")
    await _schedule(client, version_of, "2026-10-11T09:00:00Z", "Sunday")
    await _schedule(client, version_of, "2026-10-13T09:00:00Z", "Tuesday")

    listed = (await client.get(SCHEDULED_POSTS)).json()["data"]

    assert [p["parts"][0]["text"] for p in listed] == ["Sunday", "Monday", "Tuesday"]


# A minute and a half, and a year less half a minute, after the frozen 12:00:30.
@pytest.mark.parametrize(
    "payload",
    [
        {"publish_at": "2026-10-10T14:00:00Z", "publish_now": True},
        {},
        {"publish_at": "2026-10-10T14:00:00"},
    ],
)
async def test_a_request_needs_either_a_publish_time_with_a_timezone_or_publish_now(
    client, subscribed, fake_x_publisher, fixed_clock, payload, connect_x, version_of
):
    await connect_x()

    response = await client.post(
        SCHEDULED_POSTS, json={"source_version_id": await version_of("Hi."), **payload}
    )

    assert response.status_code == 422
    assert fake_x_publisher.published == []
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == []


async def test_a_user_who_is_not_subscribed_cannot_schedule(
    client, fake_x_publisher, fixed_clock, version_of
):
    response = await _schedule(client, version_of, "2026-10-10T14:00:00Z")

    assert response.status_code == 403


async def test_a_user_without_a_subscription_schedules_where_no_plans_are_sold(
    client, sells_no_plans, fake_x_publisher, fixed_clock, connect_x, version_of
):
    await connect_x()

    response = await _schedule(client, version_of, "2026-10-10T14:00:00Z")

    assert response.status_code == 201
    assert response.json()["state"] == "scheduled"


@pytest.fixture
async def version(client, subscribed, fake_x_reader, fake_llm) -> dict:
    """The first Version of a new Post written through the API, its text "Version one."."""
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    added = await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    assert added.status_code == 201, added.text
    fake_llm.replies = [written("draft one"), {"post": "Version one."}]
    started = await client.post("/api/v1/posts", json={"brief": "ship small things"})
    assert started.status_code == 201, started.text
    post = started.json()
    return {"post_id": post["id"], **post["versions"][0]}


async def test_scheduling_a_version_records_its_text_time_and_source_version(
    client, version, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()

    response = await client.post(
        SCHEDULED_POSTS,
        json={"publish_at": "2026-10-10T14:00:00Z", "source_version_id": version["id"]},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert _texts(body) == ["Version one."]
    assert body["publish_at"] == "2026-10-10T14:00:00Z"
    assert body["source_version_id"] == version["id"]
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == [body]


async def test_post_now_on_a_version_publishes_it_and_tracks_its_source(
    client, version, fake_x_publisher, clock, monkeypatch, connect_x
):
    captured = MagicMock()
    monkeypatch.setattr(publish_module, "posthog_client", captured)
    await connect_x()

    response = await client.post(
        SCHEDULED_POSTS,
        json={"publish_now": True, "source_version_id": version["id"]},
    )

    assert response.status_code == 201, response.text
    assert response.json()["state"] == "published"
    assert response.json()["source_version_id"] == version["id"]
    assert fake_x_publisher.published == [("access-1001-1", "Version one.")]
    [published] = captured.capture.call_args_list
    assert published.kwargs["properties"] == {
        "source": "final",
        "destination": "profile",
        "format": "post",
        "part_count": 1,
    }


THREAD_VERSION = ["Ship small every week.", "It's how you learn.", "Start today."]


@pytest.fixture
async def thread_version(client, subscribed, fake_x_reader, fake_llm) -> dict:
    """The first Version of a new Post started as a Thread, its text the THREAD_VERSION Parts."""
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    added = await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    assert added.status_code == 201, added.text
    fake_llm.replies = [written_thread(["one", "two", "three"]), {"parts": THREAD_VERSION}]
    started = await client.post(
        "/api/v1/posts", json={"brief": "ship small things", "format": "thread"}
    )
    assert started.status_code == 201, started.text
    return started.json()["versions"][0]


async def test_scheduling_a_thread_version_copies_its_parts_in_order_and_publishes_a_chain(
    client, db_session_maker, thread_version, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()

    response = await client.post(
        SCHEDULED_POSTS,
        json={"publish_at": "2026-10-10T12:05:00Z", "source_version_id": thread_version["id"]},
    )

    assert response.status_code == 201, response.text
    assert _texts(response.json()) == THREAD_VERSION
    fixed_clock.advance(timedelta(minutes=5))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    [listed] = (await client.get(SCHEDULED_POSTS)).json()["data"]
    assert listed["state"] == "published"
    assert [part["live"] for part in listed["parts"]] == [True, True, True]
    assert [text for _, text in fake_x_publisher.published] == THREAD_VERSION
    assert fake_x_publisher.replied_to == [None, "1890000000000000001", "1890000000000000002"]


async def test_post_now_on_a_thread_version_publishes_the_whole_thread(
    client, thread_version, fake_x_publisher, clock, connect_x
):
    await connect_x()

    response = await client.post(
        SCHEDULED_POSTS,
        json={"publish_now": True, "source_version_id": thread_version["id"]},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "published"
    assert _texts(body) == THREAD_VERSION
    assert body["x_post_url"] == FIRST_X_POST_URL
    assert [text for _, text in fake_x_publisher.published] == THREAD_VERSION
    assert fake_x_publisher.replied_to == [None, "1890000000000000001", "1890000000000000002"]


async def test_a_source_version_that_is_not_one_of_the_user_s_versions_is_refused(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()

    response = await client.post(
        SCHEDULED_POSTS,
        json={
            "publish_at": "2026-10-10T14:00:00Z",
            "source_version_id": "version_attempt_someone_else",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Version not found."
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == []


@pytest.fixture
def cap_of_two(monkeypatch):
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 2)


OCTOBER_FULL = (
    "You have 2 X posts in October 2026, the most for one month. "
    "The cap resets on November 1, 2026."
)


async def test_the_monthly_cap_counts_each_part_of_a_thread_as_an_x_post(
    client, subscribed, fake_x_publisher, fixed_clock, monkeypatch, connect_x, version_of
):
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 3)
    await connect_x()
    thread = await client.post(
        SCHEDULED_POSTS,
        json={
            "source_version_id": await version_of("One", "Two"),
            "publish_at": "2026-10-11T09:00:00Z",
        },
    )
    single = await _schedule(client, version_of, "2026-10-12T09:00:00Z", "Three")

    refused = await _schedule(client, version_of, "2026-10-13T09:00:00Z", "Four")

    assert thread.status_code == single.status_code == 201
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "You have 3 X posts in October 2026, the most for one month. "
        "The cap resets on November 1, 2026."
    )


async def test_a_thread_that_would_cross_the_monthly_cap_is_refused_before_it_is_scheduled(
    client, subscribed, fake_x_publisher, fixed_clock, monkeypatch, connect_x, version_of
):
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 3)
    await connect_x()
    first = await _schedule(client, version_of, "2026-10-11T09:00:00Z", "First")

    thread_id = await version_of("One", "Two", "Three")

    for fields in ({"publish_at": "2026-10-12T09:00:00Z"}, {"publish_now": True}):
        response = await client.post(
            SCHEDULED_POSTS, json={"source_version_id": thread_id, **fields}
        )

        assert response.status_code == 409
        assert response.json()["detail"] == (
            "These 3 Parts would take you over the cap of 3 X posts in October 2026: you have "
            "1 already. The cap resets on November 1, 2026."
        )
    assert [p["id"] for p in (await client.get(SCHEDULED_POSTS)).json()["data"]] == [
        first.json()["id"]
    ]
    assert fake_x_publisher.published == []


async def test_scheduling_into_a_full_month_is_refused_with_the_date_the_cap_resets(
    client, subscribed, fake_x_publisher, fixed_clock, cap_of_two, connect_x, version_of
):
    await connect_x()
    await _schedule(client, version_of, "2026-10-11T09:00:00Z", "First")
    await _schedule(client, version_of, "2026-10-30T09:00:00Z", "Second")

    response = await _schedule(client, version_of, "2026-10-12T09:00:00Z", "Third")

    assert response.status_code == 409
    assert response.json()["detail"] == OCTOBER_FULL
    listed = (await client.get(SCHEDULED_POSTS)).json()["data"]
    assert [p["parts"][0]["text"] for p in listed] == ["First", "Second"]


async def test_scheduled_posts_can_be_listed_by_state_in_the_same_order(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, version_of
):
    await connect_x()
    await _schedule(client, version_of, "2026-10-12T09:00:00Z", "Monday")
    await _schedule(client, version_of, "2026-10-11T09:00:00Z", "Sunday")
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    await _post_now(client, version_of, "Refused")
    fake_x_publisher.fail_publish = None
    await _post_now(client, version_of, "Went out")

    scheduled = (await client.get(SCHEDULED_POSTS, params={"state": "scheduled"})).json()["data"]
    failed = (await client.get(SCHEDULED_POSTS, params={"state": "failed"})).json()["data"]
    published = (await client.get(SCHEDULED_POSTS, params={"state": "published"})).json()["data"]

    assert [p["parts"][0]["text"] for p in scheduled] == ["Sunday", "Monday"]
    assert [p["parts"][0]["text"] for p in failed] == ["Refused"]
    assert [p["parts"][0]["text"] for p in published] == ["Went out"]


async def test_listing_by_an_unknown_state_is_refused(client, subscribed):
    response = await client.get(SCHEDULED_POSTS, params={"state": "posted"})

    assert response.status_code == 422


async def test_a_thread_scheduled_keeps_its_parts_in_order_with_none_live(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, version_of
):
    await connect_x()

    response = await client.post(
        SCHEDULED_POSTS,
        json={
            "source_version_id": await version_of("The first Part.", "The second Part."),
            "publish_at": "2026-10-10T14:00:00Z",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["parts"] == [
        {"text": "The first Part.", "live": False, "x_post_url": None},
        {"text": "The second Part.", "live": False, "x_post_url": None},
    ]
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == [response.json()]


async def test_post_now_makes_its_one_part_live_with_its_link_on_x(
    client, subscribed, fake_x_publisher, clock, connect_x, version_of
):
    await connect_x()

    response = await _post_now(client, version_of, "Out now.")

    assert response.json()["parts"] == [
        {"text": "Out now.", "live": True, "x_post_url": FIRST_X_POST_URL}
    ]


async def test_a_part_over_the_limit_is_refused_naming_the_part(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, version_of
):
    await connect_x()

    response = await client.post(
        SCHEDULED_POSTS,
        json={
            "source_version_id": await version_of("Fine.", "a" * 281),
            "publish_at": "2026-10-10T14:00:00Z",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Part 2 is 281 characters by X's count, over the 280 limit."
    )
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == []
