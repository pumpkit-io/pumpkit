"""Scheduled posts that go to a Community instead of the User's profile, through the HTTP API."""

from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

import pumpkit.scheduling.publish as publish_module
from pumpkit.core.config import settings
from pumpkit.x_connection.x_publisher import XPostRejectedError

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
COMMUNITY_ID = "1493446837214187523"
COMMUNITY_URL = f"https://x.com/i/communities/{COMMUNITY_ID}"
# What X answered a non-member in spike #124.
NOT_A_MEMBER = XPostRejectedError(403, "You do not have permission to create this Tweet.")


@pytest.fixture(autouse=True)
def known_community(fake_x_reader) -> None:
    fake_x_reader.communities[COMMUNITY_ID] = "Build in Public"


async def _post_now(client: AsyncClient, text: str = "Hello Community.", **destination):
    return await client.post(
        SCHEDULED_POSTS, json={"parts": [text], "publish_now": True, **destination}
    )


@pytest.mark.parametrize("share_with_followers", [True, False])
async def test_post_now_into_a_community_publishes_it_there(
    client, subscribed, fake_x_publisher, clock, share_with_followers, connect_x
):
    await connect_x()

    response = await _post_now(
        client,
        community=COMMUNITY_URL,
        share_with_followers=share_with_followers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "published"
    assert body["community"] == {
        "id": COMMUNITY_ID,
        "name": "Build in Public",
        "url": COMMUNITY_URL,
    }
    assert body["share_with_followers"] is share_with_followers
    assert fake_x_publisher.published == [("access-1001-1", "Hello Community.")]
    assert fake_x_publisher.published_to == [(COMMUNITY_ID, share_with_followers)]
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == [body]


async def test_post_now_without_a_community_publishes_on_the_profile(
    client, subscribed, fake_x_publisher, clock, connect_x
):
    await connect_x()

    body = (await _post_now(client)).json()

    assert body["community"] is None
    assert body["share_with_followers"] is False
    assert fake_x_publisher.published_to == [(None, False)]


async def test_text_that_is_not_a_community_is_refused(
    client, subscribed, fake_x_publisher, clock, connect_x
):
    await connect_x()

    response = await _post_now(client, community="https://x.com/levelsio")

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "That isn't a Community. Paste its URL from X, like https://x.com/i/communities/123, "
        "or its ID."
    )
    assert fake_x_publisher.published == []
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == []


async def test_a_community_post_x_refuses_for_a_non_member_fails_with_a_membership_hint(
    client, subscribed, fake_x_publisher, clock, monkeypatch, connect_x
):
    captured = MagicMock()
    monkeypatch.setattr(publish_module, "posthog_client", captured)
    await connect_x()
    fake_x_publisher.fail_publish = NOT_A_MEMBER

    response = await _post_now(client, community=COMMUNITY_ID)

    assert response.status_code == 201, response.text
    assert response.json()["state"] == "failed"
    assert response.json()["failed_reason"] == (
        "X refused the post: You do not have permission to create this Tweet. Check that your "
        "X account is a member of this Community and allowed to post in it."
    )
    captured.capture.assert_called_once_with(
        "scheduled_post_failed",
        distinct_id=subscribed.user_id,
        properties={"reason": "refused_by_x", "format": "post", "part_count": 1},
    )


@pytest.mark.parametrize(
    ("refusal", "community"),
    [
        (NOT_A_MEMBER, None),
        (XPostRejectedError(400, "Duplicate content."), COMMUNITY_ID),
    ],
    ids=["profile post refused with 403", "community post refused with 400"],
)
async def test_other_refusals_fail_without_the_membership_hint(
    client, subscribed, fake_x_publisher, clock, refusal, community, connect_x
):
    await connect_x()
    fake_x_publisher.fail_publish = refusal

    response = await _post_now(client, community=community)

    assert response.json()["state"] == "failed"
    assert response.json()["failed_reason"] == f"X refused the post: {refusal.message}"


async def test_community_posts_count_towards_the_monthly_cap(
    client, subscribed, fake_x_publisher, fixed_clock, monkeypatch, connect_x
):
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 2)
    await connect_x()
    community = COMMUNITY_ID
    await _post_now(client, "First", community=community)
    await client.post(
        SCHEDULED_POSTS,
        json={"parts": ["Second"], "publish_at": "2026-10-11T09:00:00Z", "community": community},
    )

    response = await _post_now(client, "Third")

    assert response.status_code == 409
    assert response.json()["detail"].startswith("You have 2 X posts in October 2026")


async def test_a_community_post_is_tracked_with_where_it_went(
    client, subscribed, fake_x_publisher, clock, monkeypatch, connect_x
):
    captured = MagicMock()
    monkeypatch.setattr(publish_module, "posthog_client", captured)
    await connect_x()
    community = COMMUNITY_ID

    await _post_now(client, "Shared", community=community, share_with_followers=True)
    await _post_now(client, "Kept to the Community", community=community)
    await _post_now(client, "On the profile")

    assert [call.kwargs["properties"] for call in captured.capture.call_args_list] == [
        {
            "source": "typed",
            "destination": "community",
            "share_with_followers": True,
            "format": "post",
            "part_count": 1,
        },
        {
            "source": "typed",
            "destination": "community",
            "share_with_followers": False,
            "format": "post",
            "part_count": 1,
        },
        {"source": "typed", "destination": "profile", "format": "post", "part_count": 1},
    ]
