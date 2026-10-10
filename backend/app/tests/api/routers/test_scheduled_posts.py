from datetime import timedelta
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient

import app.publishing.publish as publish_module
from app.core.x_publisher import (
    XNotReceivedError,
    XOutcomeUnknownError,
    XPostRejectedError,
    XRateLimitedError,
    XReconnectNeededError,
)

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
async def test_a_post_x_never_took_fails_saying_nothing_was_published(
    client, subscribed, fake_x_publisher, clock, error
):
    await _connect_x(client)
    fake_x_publisher.fail_publish = error

    response = await _post_now(client)

    assert response.json()["state"] == "failed"
    assert response.json()["failed_reason"] == (
        "Not published: X was busy or unreachable. Try again in a few minutes."
    )
    assert len(fake_x_publisher.published) == 1


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
