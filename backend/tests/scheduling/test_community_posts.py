"""Scheduled posts that go to a Community instead of the User's profile, through the HTTP API."""

from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient

import pumpkit.scheduling.publish as publish_module
from pumpkit.core.config import settings

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
COMMUNITY_ID = "1493446837214187523"
COMMUNITY_URL = f"https://x.com/i/communities/{COMMUNITY_ID}"


async def _connect_x(client: AsyncClient) -> None:
    started = await client.post("/api/v1/x-connection/authorizations")
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
    completed = await client.post(
        "/api/v1/x-connection/authorizations/complete", json={"code": "c", "state": state}
    )
    assert completed.status_code == 200, completed.text


async def _post_now(client: AsyncClient, text: str = "Hello Community.", **destination):
    return await client.post(
        SCHEDULED_POSTS, json={"text": text, "publish_now": True, **destination}
    )


@pytest.mark.parametrize("share_with_followers", [True, False])
async def test_post_now_into_a_community_publishes_it_there(
    client, subscribed, fake_x_publisher, clock, share_with_followers
):
    await _connect_x(client)

    response = await _post_now(
        client,
        community={"id": COMMUNITY_ID, "name": None},
        share_with_followers=share_with_followers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "published"
    assert body["community"] == {"id": COMMUNITY_ID, "name": None, "url": COMMUNITY_URL}
    assert body["share_with_followers"] is share_with_followers
    assert fake_x_publisher.published == [("access-1001-1", "Hello Community.")]
    assert fake_x_publisher.published_to == [(COMMUNITY_ID, share_with_followers)]
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == [body]


async def test_post_now_without_a_community_publishes_on_the_profile(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)

    body = (await _post_now(client)).json()

    assert body["community"] is None
    assert body["share_with_followers"] is False
    assert fake_x_publisher.published_to == [(None, False)]


async def test_a_community_s_name_is_kept_as_given(client, subscribed, fake_x_publisher, clock):
    await _connect_x(client)

    body = (await _post_now(client, community={"id": COMMUNITY_ID, "name": "Indie makers"})).json()

    assert body["community"]["name"] == "Indie makers"


async def test_sharing_with_followers_without_a_community_posts_on_the_profile(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)

    body = (await _post_now(client, share_with_followers=True)).json()

    assert body["community"] is None
    assert body["share_with_followers"] is False
    assert fake_x_publisher.published_to == [(None, False)]


@pytest.mark.parametrize(
    "community_id",
    ["", "abc", "12345678901234567890", COMMUNITY_URL, " 123"],
)
async def test_a_community_id_that_is_not_1_to_19_digits_is_refused(
    client, subscribed, fake_x_publisher, clock, community_id
):
    await _connect_x(client)

    response = await _post_now(client, community={"id": community_id, "name": None})

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "That isn't a Community. Paste its URL from X, like https://x.com/i/communities/123, "
        "or its ID."
    )
    assert fake_x_publisher.published == []
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == []


async def test_a_community_post_follows_the_x_account_s_length_limit(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)

    response = await _post_now(client, "a" * 281, community={"id": COMMUNITY_ID, "name": None})

    assert response.status_code == 422
    assert (
        response.json()["detail"] == "This post is 281 characters by X's count, over the 280 limit."
    )
    assert fake_x_publisher.published == []


async def test_community_posts_count_towards_the_monthly_cap(
    client, subscribed, fake_x_publisher, fixed_clock, monkeypatch
):
    monkeypatch.setattr(settings, "SCHEDULED_POSTS_MONTHLY_CAP", 2)
    await _connect_x(client)
    community = {"id": COMMUNITY_ID, "name": None}
    await _post_now(client, "First", community=community)
    await client.post(
        SCHEDULED_POSTS,
        json={"text": "Second", "publish_at": "2026-10-11T09:00:00Z", "community": community},
    )

    response = await _post_now(client, "Third")

    assert response.status_code == 409
    assert response.json()["detail"].startswith("You have 2 Scheduled posts in October 2026")


async def test_a_community_post_is_tracked_with_where_it_went(
    client, subscribed, fake_x_publisher, clock, monkeypatch
):
    captured = MagicMock()
    monkeypatch.setattr(publish_module, "posthog_client", captured)
    await _connect_x(client)
    community = {"id": COMMUNITY_ID, "name": None}

    await _post_now(client, "Shared", community=community, share_with_followers=True)
    await _post_now(client, "Kept to the Community", community=community)
    await _post_now(client, "On the profile")

    assert [call.kwargs["properties"] for call in captured.capture.call_args_list] == [
        {"source": "typed", "destination": "community", "share_with_followers": True},
        {"source": "typed", "destination": "community", "share_with_followers": False},
        {"source": "typed", "destination": "profile"},
    ]
