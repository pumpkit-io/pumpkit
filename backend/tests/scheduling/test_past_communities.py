"""The Communities a User posted to before, offered again, through the HTTP API."""

from datetime import timedelta
from typing import Optional

import pytest
from httpx import AsyncClient

from pumpkit.authors.x_reader import FakeXReader
from pumpkit.x_connection.x_publisher import XAccount

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
PAST_COMMUNITIES = "/api/v1/scheduled-posts/communities"
MAKERS = "1493446837214187523"
WRITERS = "1600000000000000001"


@pytest.fixture(autouse=True)
def known_communities(fake_x_reader) -> None:
    fake_x_reader.communities.update({MAKERS: "Indie makers", WRITERS: "Writers"})


async def _post_now_into(
    client: AsyncClient, reader: FakeXReader, community_id: str, name: Optional[str]
) -> None:
    """Into the Community X now names `name`, or that X can't be read for when it's None."""
    reader.fail = name is None
    if name is not None:
        reader.communities[community_id] = name
    response = await client.post(
        SCHEDULED_POSTS,
        json={"parts": ["Hello"], "publish_now": True, "community": community_id},
    )
    assert response.status_code == 201, response.text


async def _past_communities(client: AsyncClient) -> list[dict]:
    response = await client.get(PAST_COMMUNITIES)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_past_communities_come_most_recently_used_first_each_once(
    client, fake_x_reader, subscribed, fake_x_publisher, clock, connect_x
):
    await connect_x()
    await _post_now_into(client, fake_x_reader, MAKERS, "Indie makers")
    clock.advance(timedelta(minutes=1))
    await _post_now_into(client, fake_x_reader, WRITERS, "Writers")
    clock.advance(timedelta(minutes=1))
    await _post_now_into(client, fake_x_reader, MAKERS, "Indie makers")

    assert await _past_communities(client) == [
        {"id": MAKERS, "name": "Indie makers", "url": f"https://x.com/i/communities/{MAKERS}"},
        {"id": WRITERS, "name": "Writers", "url": f"https://x.com/i/communities/{WRITERS}"},
    ]


async def test_a_scheduled_post_counts_as_a_use_too(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    publish_at = "2026-10-11T09:00:00Z"

    response = await client.post(
        SCHEDULED_POSTS,
        json={"parts": ["Later"], "publish_at": publish_at, "community": MAKERS},
    )

    assert response.status_code == 201, response.text
    assert [c["id"] for c in await _past_communities(client)] == [MAKERS]


async def test_editing_a_post_into_a_community_counts_as_its_latest_use(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    later = {"parts": ["Later"], "publish_at": "2026-10-11T09:00:00Z"}
    earlier_post = (await client.post(SCHEDULED_POSTS, json=later)).json()
    fixed_clock.advance(timedelta(minutes=1))
    await client.post(SCHEDULED_POSTS, json={**later, "community": MAKERS})
    fixed_clock.advance(timedelta(minutes=1))

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{earlier_post['id']}", json={"community": WRITERS}
    )

    assert response.status_code == 200, response.text
    assert [c["id"] for c in await _past_communities(client)] == [WRITERS, MAKERS]


async def test_changing_only_the_share_with_followers_choice_is_no_new_use(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    later = {"parts": ["Later"], "publish_at": "2026-10-11T09:00:00Z"}
    makers_post = (await client.post(SCHEDULED_POSTS, json={**later, "community": MAKERS})).json()
    fixed_clock.advance(timedelta(minutes=1))
    await client.post(SCHEDULED_POSTS, json={**later, "community": WRITERS})
    fixed_clock.advance(timedelta(minutes=1))

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{makers_post['id']}", json={"share_with_followers": True}
    )

    assert response.status_code == 200, response.text
    assert [c["id"] for c in await _past_communities(client)] == [WRITERS, MAKERS]


async def test_a_past_community_shows_the_latest_name_stored_for_it(
    client, fake_x_reader, subscribed, fake_x_publisher, clock, connect_x
):
    await connect_x()
    await _post_now_into(client, fake_x_reader, MAKERS, "Makers")
    clock.advance(timedelta(minutes=1))
    await _post_now_into(client, fake_x_reader, MAKERS, "Indie makers")
    clock.advance(timedelta(minutes=1))
    await _post_now_into(client, fake_x_reader, MAKERS, None)

    assert [c["name"] for c in await _past_communities(client)] == ["Indie makers"]


async def test_a_past_community_never_named_has_no_name(
    client, fake_x_reader, subscribed, fake_x_publisher, clock, connect_x
):
    await connect_x()
    await _post_now_into(client, fake_x_reader, MAKERS, None)

    assert [c["name"] for c in await _past_communities(client)] == [None]


async def test_profile_posts_add_no_past_community(
    client, subscribed, fake_x_publisher, clock, connect_x
):
    await connect_x()
    await client.post(SCHEDULED_POSTS, json={"parts": ["Hello"], "publish_now": True})

    assert await _past_communities(client) == []


async def test_only_the_connected_x_account_s_communities_are_offered(
    client, fake_x_reader, subscribed, fake_x_publisher, clock, connect_x
):
    await connect_x()
    await _post_now_into(client, fake_x_reader, MAKERS, "Indie makers")
    fake_x_publisher.account = XAccount(user_id="2002", handle="grace", subscription_type="None")
    await connect_x()
    await _post_now_into(client, fake_x_reader, WRITERS, "Writers")

    assert [c["id"] for c in await _past_communities(client)] == [WRITERS]


async def test_without_an_x_connection_no_past_community_is_offered(client, subscribed):
    assert await _past_communities(client) == []
