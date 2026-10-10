from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.publishing.publish as publish_module
from app.core.config import settings
from app.core.x_publisher import (
    XAccount,
    XNotReceivedError,
    XOutcomeUnknownError,
    XPostRejectedError,
    XRateLimitedError,
    XReconnectNeededError,
)
from app.core.x_reader import FetchedPost
from app.db.models import XConnection
from app.publishing.publisher import run_pass

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
RECONNECT_REASON = (
    "Not published: X no longer accepts Pumpkit's access to your account. Reconnect X, then "
    "reschedule it."
)


async def _connect_x(client: AsyncClient) -> None:
    started = await client.post("/api/v1/x-connection/authorizations")
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
    completed = await client.post(
        "/api/v1/x-connection/authorizations/complete", json={"code": "c", "state": state}
    )
    assert completed.status_code == 200, completed.text


def _iso(dt) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def _post_now(client: AsyncClient, text: str = "Shipping today."):
    return await client.post(SCHEDULED_POSTS, json={"text": text, "publish_now": True})


async def test_post_now_publishes_the_text_and_lists_it_as_published(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)

    response = await _post_now(client, "Shipping the new onboarding today.")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "published"
    assert body["text"] == "Shipping the new onboarding today."
    assert body["published_at"] == _iso(clock())
    assert body["x_post_url"] == "https://x.com/i/web/status/1890000000000000001"
    assert body["failed_reason"] is None
    assert fake_x_publisher.refreshes == []
    assert fake_x_publisher.published == [("access-1001-1", "Shipping the new onboarding today.")]
    listed = (await client.get(SCHEDULED_POSTS)).json()["data"]
    assert listed == [body]


async def test_post_now_uses_a_fresh_access_token_without_refreshing_it(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    clock.advance(timedelta(hours=1, minutes=54))

    await _post_now(client)

    assert fake_x_publisher.refreshes == []
    assert fake_x_publisher.published[0][0] == "access-1001-1"


async def test_a_token_near_expiry_is_refreshed_and_the_rotated_refresh_token_kept(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    clock.advance(timedelta(hours=1, minutes=56))
    first = await _post_now(client, "First")
    clock.advance(timedelta(hours=1, minutes=56))

    second = await _post_now(client, "Second")

    assert first.json()["state"] == second.json()["state"] == "published"
    assert fake_x_publisher.refreshes == ["refresh-1001-1", "refresh-1001-2"]
    assert fake_x_publisher.published == [("access-1001-2", "First"), ("access-1001-3", "Second")]


async def test_a_token_refresh_rereads_the_x_account_s_subscription_type(
    client, db, user, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    fake_x_publisher.account = XAccount(user_id="1001", handle="ada", subscription_type="Premium")
    clock.advance(timedelta(hours=1, minutes=56))

    await _post_now(client)

    connection = (
        await db.execute(select(XConnection).where(XConnection.user_id == user.id))
    ).scalar_one()
    assert connection.subscription_type == "Premium"


async def test_a_failed_subscription_type_read_keeps_the_refreshed_tokens_and_publishes(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    fake_x_publisher.fail_fetch_account = XNotReceivedError("ConnectError")
    clock.advance(timedelta(hours=1, minutes=56))

    first = await _post_now(client, "First")
    clock.advance(timedelta(hours=1, minutes=56))
    second = await _post_now(client, "Second")

    assert first.json()["state"] == second.json()["state"] == "published"
    assert fake_x_publisher.refreshes == ["refresh-1001-1", "refresh-1001-2"]


async def test_post_now_without_an_x_connection_is_refused(
    client, subscribed, fake_x_publisher, clock
):
    response = await _post_now(client)

    assert response.status_code == 409
    assert response.json()["detail"] == "Connect your X account first."
    assert fake_x_publisher.published == []
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == []


async def test_a_text_over_the_limit_by_x_s_count_is_refused(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    # 276 code points, but CJK characters count two each: 281 by X's count.
    text = "a" * 270 + " 日本語のテ"

    response = await _post_now(client, text)

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "This post is 281 characters by X's count, over the 280 limit."
    )
    assert fake_x_publisher.published == []


async def test_a_text_at_the_limit_by_x_s_count_is_published_however_long_its_url(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    text = "a" * 256 + " https://example.com/" + "x" * 100

    response = await _post_now(client, text)

    assert response.status_code == 201
    assert response.json()["state"] == "published"


async def test_a_blank_text_is_refused(client, subscribed, fake_x_publisher, clock):
    await _connect_x(client)

    response = await _post_now(client, "   ")

    assert response.status_code == 422
    assert fake_x_publisher.published == []


async def test_a_user_who_is_not_subscribed_cannot_post_now(client, fake_x_publisher, clock):
    response = await _post_now(client)

    assert response.status_code == 403
    assert fake_x_publisher.published == []


async def test_a_post_x_refuses_fails_with_x_s_own_words(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    fake_x_publisher.fail_publish = XPostRejectedError(
        403, "You are not allowed to create a Tweet with duplicate content."
    )

    response = await _post_now(client)

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "failed"
    assert body["failed_reason"] == (
        "X refused the post: You are not allowed to create a Tweet with duplicate content."
    )
    assert body["x_post_url"] is None and body["published_at"] is None
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == [body]


async def test_a_post_whose_outcome_is_unknown_fails_telling_the_user_to_check_x(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    fake_x_publisher.fail_publish = XOutcomeUnknownError("X answered HTTP 503")

    response = await _post_now(client)

    assert response.json()["state"] == "failed"
    assert response.json()["failed_reason"] == (
        "X didn't confirm this post. It may have been published, check your X profile."
    )
    assert len(fake_x_publisher.published) == 1


@pytest.mark.parametrize("error", [XRateLimitedError("429"), XNotReceivedError("ConnectError")])
async def test_a_post_now_x_never_took_goes_back_to_scheduled_for_the_publisher_to_retry(
    client, db_session_maker, subscribed, fake_x_publisher, clock, error
):
    await _connect_x(client)
    fake_x_publisher.fail_publish = error

    response = await _post_now(client)

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
    client, db_session_maker, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    fake_x_publisher.fail_publish = XRateLimitedError("429")
    await _post_now(client)

    for _ in range(32):
        clock.advance(timedelta(seconds=30))
        await run_pass(db_session_maker, fake_x_publisher, clock)

    [listed] = (await client.get(SCHEDULED_POSTS)).json()["data"]
    assert listed["state"] == "failed"
    assert listed["failed_reason"] == (
        "Not published: X was busy or unreachable. Try again in a few minutes."
    )


async def test_revoked_access_fails_the_post_and_asks_the_user_to_reconnect(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    fake_x_publisher.fail_publish = XReconnectNeededError("401")

    response = await _post_now(client)

    assert response.json()["state"] == "failed"
    assert response.json()["failed_reason"] == RECONNECT_REASON
    assert (await client.get("/api/v1/x-connection")).json()["needs_reconnect"] is True
    fake_x_publisher.fail_publish = None
    again = await _post_now(client)
    assert again.status_code == 409
    assert again.json()["detail"] == (
        "X no longer accepts Pumpkit's access to your account. Reconnect X first."
    )
    assert len(fake_x_publisher.published) == 1


async def test_a_refresh_token_x_refuses_fails_the_post_and_asks_the_user_to_reconnect(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    clock.advance(timedelta(hours=2))
    fake_x_publisher.fail_refresh = XReconnectNeededError("invalid_grant")

    response = await _post_now(client)

    assert response.json()["state"] == "failed"
    assert response.json()["failed_reason"] == RECONNECT_REASON
    assert fake_x_publisher.published == []
    assert (await client.get("/api/v1/x-connection")).json()["needs_reconnect"] is True


async def test_reconnecting_clears_the_reconnect_flag(client, subscribed, fake_x_publisher, clock):
    await _connect_x(client)
    fake_x_publisher.fail_publish = XReconnectNeededError("401")
    await _post_now(client)
    fake_x_publisher.fail_publish = None

    await _connect_x(client)

    assert (await client.get("/api/v1/x-connection")).json()["needs_reconnect"] is False
    assert (await _post_now(client)).json()["state"] == "published"


async def test_a_user_whose_subscription_ended_still_sees_their_scheduled_posts(
    client, db, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    published = (await _post_now(client, "Went out")).json()
    clock.advance(timedelta(minutes=1))
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    failed = (await _post_now(client, "Refused")).json()
    subscribed.status = "canceled"
    await db.commit()

    response = await client.get(SCHEDULED_POSTS)

    assert response.status_code == 200
    assert response.json()["data"] == [failed, published]


async def test_published_and_failed_are_tracked_for_analytics(
    client, subscribed, fake_x_publisher, clock, monkeypatch
):
    captured = MagicMock()
    monkeypatch.setattr(publish_module, "posthog_client", captured)
    await _connect_x(client)
    await _post_now(client)
    fake_x_publisher.fail_publish = XOutcomeUnknownError("timeout")

    await _post_now(client)

    assert [call.args[0] for call in captured.capture.call_args_list] == [
        "scheduled_post_published",
        "scheduled_post_failed",
    ]
    published, failed = captured.capture.call_args_list
    assert published.kwargs["properties"] == {"source": "typed"}
    assert failed.kwargs["properties"] == {"reason": "outcome_unknown"}


async def _schedule(client: AsyncClient, publish_at: str, text: str = "Later today."):
    return await client.post(SCHEDULED_POSTS, json={"text": text, "publish_at": publish_at})


async def test_a_post_scheduled_for_later_is_listed_as_upcoming_and_not_published(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)

    response = await _schedule(client, "2026-10-10T14:00:00Z", "Launch day.")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "scheduled"
    assert body["text"] == "Launch day."
    assert body["publish_at"] == "2026-10-10T14:00:00Z"
    assert body["published_at"] is None and body["x_post_url"] is None
    assert fake_x_publisher.published == []
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == [body]


async def test_a_publish_time_in_the_browser_s_timezone_is_stored_in_utc(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)

    response = await _schedule(client, "2026-10-10T16:00:00+02:00")

    assert response.json()["publish_at"] == "2026-10-10T14:00:00Z"


async def test_upcoming_scheduled_posts_are_listed_soonest_first(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    await _schedule(client, "2026-10-12T09:00:00Z", "Monday")
    await _schedule(client, "2026-10-11T09:00:00Z", "Sunday")
    await _schedule(client, "2026-10-13T09:00:00Z", "Tuesday")

    listed = (await client.get(SCHEDULED_POSTS)).json()["data"]

    assert [p["text"] for p in listed] == ["Sunday", "Monday", "Tuesday"]


# A minute and a half, and a year less half a minute, after the frozen 12:00:30.
@pytest.mark.parametrize("publish_at", ["2026-10-10T12:02:00Z", "2027-10-10T12:00:00Z"])
async def test_times_at_the_edges_of_the_window_are_accepted(
    client, subscribed, fake_x_publisher, fixed_clock, publish_at
):
    await _connect_x(client)

    response = await _schedule(client, publish_at)

    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    ("publish_at", "detail"),
    [
        ("2026-10-10T12:01:00Z", "Pick a time at least a minute from now."),
        ("2026-10-10T11:00:00Z", "Pick a time at least a minute from now."),
        ("2027-10-10T12:01:00Z", "Pick a time within a year from now."),
        ("2026-10-10T14:00:30Z", "Pick a time on a whole minute."),
    ],
)
async def test_times_outside_the_window_or_off_the_minute_are_refused(
    client, subscribed, fake_x_publisher, fixed_clock, publish_at, detail
):
    await _connect_x(client)

    response = await _schedule(client, publish_at)

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "Both", "publish_at": "2026-10-10T14:00:00Z", "publish_now": True},
        {"text": "Neither"},
        {"text": "No timezone", "publish_at": "2026-10-10T14:00:00"},
    ],
)
async def test_a_request_needs_either_a_publish_time_with_a_timezone_or_publish_now(
    client, subscribed, fake_x_publisher, fixed_clock, payload
):
    await _connect_x(client)

    response = await client.post(SCHEDULED_POSTS, json=payload)

    assert response.status_code == 422
    assert fake_x_publisher.published == []
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == []


async def test_scheduling_follows_the_same_x_connection_and_length_rules_as_post_now(
    client, subscribed, fake_x_publisher, fixed_clock
):
    unconnected = await _schedule(client, "2026-10-10T14:00:00Z")
    await _connect_x(client)
    too_long = await _schedule(client, "2026-10-10T14:00:00Z", "a" * 281)

    assert unconnected.status_code == 409
    assert unconnected.json()["detail"] == "Connect your X account first."
    assert too_long.status_code == 422
    assert too_long.json()["detail"] == (
        "This post is 281 characters by X's count, over the 280 limit."
    )


async def test_a_user_who_is_not_subscribed_cannot_schedule(client, fake_x_publisher, fixed_clock):
    response = await _schedule(client, "2026-10-10T14:00:00Z")

    assert response.status_code == 403


@pytest.fixture
async def final(client, subscribed, fake_x_reader, fake_llm) -> dict:
    """The first Version of a new Post, whose Final is "The final, version one."."""
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    added = await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    assert added.status_code == 201, added.text
    fake_llm.replies = [{"post": "draft one"}, {"post": "The final, version one."}]
    started = await client.post("/api/v1/posts", json={"brief": "ship small things"})
    assert started.status_code == 201, started.text
    post = started.json()
    return {"post_id": post["id"], **post["versions"][0]}


async def test_scheduling_a_final_records_its_text_time_and_source_version(
    client, final, fake_x_publisher, fixed_clock
):
    await _connect_x(client)

    response = await client.post(
        SCHEDULED_POSTS,
        json={
            "text": final["final"],
            "publish_at": "2026-10-10T14:00:00Z",
            "source_version_id": final["id"],
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["text"] == "The final, version one."
    assert body["publish_at"] == "2026-10-10T14:00:00Z"
    assert body["source_version_id"] == final["id"]
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == [body]


async def test_feedback_on_the_post_afterwards_leaves_the_scheduled_post_s_text_alone(
    client, final, fake_llm, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    await client.post(
        SCHEDULED_POSTS,
        json={
            "text": final["final"],
            "publish_at": "2026-10-10T14:00:00Z",
            "source_version_id": final["id"],
        },
    )
    fake_llm.replies = [{"post": "draft two"}, {"post": "The final, version two."}]

    revised = await client.post(
        f"/api/v1/posts/{final['post_id']}/versions", json={"feedback": "punchier"}
    )

    assert revised.status_code == 201, revised.text
    [listed] = (await client.get(SCHEDULED_POSTS)).json()["data"]
    assert listed["text"] == "The final, version one."
    assert listed["source_version_id"] == final["id"]


async def test_post_now_on_a_final_publishes_it_and_tracks_it_as_from_a_final(
    client, final, fake_x_publisher, clock, monkeypatch
):
    captured = MagicMock()
    monkeypatch.setattr(publish_module, "posthog_client", captured)
    await _connect_x(client)

    response = await client.post(
        SCHEDULED_POSTS,
        json={"text": final["final"], "publish_now": True, "source_version_id": final["id"]},
    )

    assert response.status_code == 201, response.text
    assert response.json()["state"] == "published"
    assert response.json()["source_version_id"] == final["id"]
    assert fake_x_publisher.published == [("access-1001-1", "The final, version one.")]
    [published] = captured.capture.call_args_list
    assert published.kwargs["properties"] == {"source": "final"}


async def test_a_typed_scheduled_post_has_no_source_version(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)

    response = await _schedule(client, "2026-10-10T14:00:00Z")

    assert response.json()["source_version_id"] is None


async def test_a_source_version_that_is_not_one_of_the_user_s_versions_is_refused(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)

    response = await client.post(
        SCHEDULED_POSTS,
        json={
            "text": "Not mine.",
            "publish_at": "2026-10-10T14:00:00Z",
            "source_version_id": "version_attempt_someone_else",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Version not found."
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == []


@pytest.fixture
def cap_of_two(monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULED_POSTS_MONTHLY_CAP", 2)


OCTOBER_FULL = (
    "You have 2 Scheduled posts in October 2026, the most for one month. "
    "The cap resets on November 1, 2026."
)


async def test_scheduling_into_a_full_month_is_refused_with_the_date_the_cap_resets(
    client, subscribed, fake_x_publisher, fixed_clock, cap_of_two
):
    await _connect_x(client)
    await _schedule(client, "2026-10-11T09:00:00Z", "First")
    await _schedule(client, "2026-10-30T09:00:00Z", "Second")

    response = await _schedule(client, "2026-10-12T09:00:00Z", "Third")

    assert response.status_code == 409
    assert response.json()["detail"] == OCTOBER_FULL
    listed = (await client.get(SCHEDULED_POSTS)).json()["data"]
    assert [p["text"] for p in listed] == ["First", "Second"]


async def test_post_now_in_a_full_month_is_refused_and_nothing_is_published(
    client, subscribed, fake_x_publisher, fixed_clock, cap_of_two
):
    await _connect_x(client)
    await _schedule(client, "2026-10-11T09:00:00Z", "First")
    await _schedule(client, "2026-10-12T09:00:00Z", "Second")

    response = await _post_now(client)

    assert response.status_code == 409
    assert response.json()["detail"] == OCTOBER_FULL
    assert fake_x_publisher.published == []


async def test_published_and_failed_scheduled_posts_count_towards_the_cap(
    client, subscribed, fake_x_publisher, fixed_clock, cap_of_two
):
    await _connect_x(client)
    published = await _post_now(client, "Out")
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Duplicate content.")
    failed = await _post_now(client, "Refused")

    response = await _schedule(client, "2026-10-11T09:00:00Z")

    assert published.json()["state"] == "published"
    assert failed.json()["state"] == "failed"
    assert response.status_code == 409
    assert response.json()["detail"] == OCTOBER_FULL


async def test_a_scheduled_post_for_next_month_is_accepted_while_this_month_is_full(
    client, subscribed, fake_x_publisher, fixed_clock, cap_of_two
):
    await _connect_x(client)
    await _schedule(client, "2026-10-11T09:00:00Z")
    await _schedule(client, "2026-10-12T09:00:00Z")

    response = await _schedule(client, "2026-11-01T00:00:00Z")

    assert response.status_code == 201, response.text


async def test_months_are_counted_in_utc(
    client, subscribed, fake_x_publisher, fixed_clock, cap_of_two
):
    await _connect_x(client)
    await _schedule(client, "2026-10-11T09:00:00Z")
    await _schedule(client, "2026-10-31T23:59:00Z")

    # November 1 in Rome, still October 31 in UTC.
    rome_november = await _schedule(client, "2026-11-01T00:30:00+01:00")
    new_york_october = await _schedule(client, "2026-10-31T20:00:00-04:00")

    assert rome_november.status_code == 409
    assert rome_november.json()["detail"] == OCTOBER_FULL
    assert new_york_october.status_code == 201, new_york_october.text
    assert new_york_october.json()["publish_at"] == "2026-11-01T00:00:00Z"


async def test_a_full_december_resets_on_january_1(
    client, subscribed, fake_x_publisher, fixed_clock, cap_of_two
):
    await _connect_x(client)
    await _schedule(client, "2026-12-01T00:00:00Z")
    await _schedule(client, "2026-12-31T23:59:00Z")

    response = await _schedule(client, "2026-12-15T09:00:00Z")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "You have 2 Scheduled posts in December 2026, the most for one month. "
        "The cap resets on January 1, 2027."
    )


async def test_post_now_works_again_once_the_utc_month_turns(
    client, subscribed, fake_x_publisher, fixed_clock, cap_of_two
):
    await _connect_x(client)
    await _schedule(client, "2026-10-11T09:00:00Z")
    await _schedule(client, "2026-10-12T09:00:00Z")
    # To 2026-10-31 23:59:30 UTC.
    fixed_clock.advance(timedelta(days=21, hours=11, minutes=59))
    before = await _post_now(client)
    fixed_clock.advance(timedelta(minutes=1))

    after = await _post_now(client)

    assert before.status_code == 409
    assert after.status_code == 201, after.text
    assert after.json()["publish_at"] == "2026-11-01T00:00:00Z"
    assert after.json()["state"] == "published"


async def test_scheduled_posts_can_be_listed_by_state_in_the_same_order(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    await _schedule(client, "2026-10-12T09:00:00Z", "Monday")
    await _schedule(client, "2026-10-11T09:00:00Z", "Sunday")
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    await _post_now(client, "Refused")
    fake_x_publisher.fail_publish = None
    await _post_now(client, "Went out")

    scheduled = (await client.get(SCHEDULED_POSTS, params={"state": "scheduled"})).json()["data"]
    failed = (await client.get(SCHEDULED_POSTS, params={"state": "failed"})).json()["data"]
    published = (await client.get(SCHEDULED_POSTS, params={"state": "published"})).json()["data"]

    assert [p["text"] for p in scheduled] == ["Sunday", "Monday"]
    assert [p["text"] for p in failed] == ["Refused"]
    assert [p["text"] for p in published] == ["Went out"]


async def test_listing_by_an_unknown_state_is_refused(client, subscribed):
    response = await client.get(SCHEDULED_POSTS, params={"state": "posted"})

    assert response.status_code == 422
