"""The Communities a User posted to before, offered again, through the HTTP API."""

from datetime import timedelta
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from httpx import AsyncClient

from pumpkit.x_connection.x_publisher import XAccount

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
PAST_COMMUNITIES = "/api/v1/scheduled-posts/communities"
MAKERS = "1493446837214187523"
WRITERS = "1600000000000000001"


async def _connect_x(client: AsyncClient) -> None:
    started = await client.post("/api/v1/x-connection/authorizations")
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
    completed = await client.post(
        "/api/v1/x-connection/authorizations/complete", json={"code": "c", "state": state}
    )
    assert completed.status_code == 200, completed.text


async def _post_now_into(client: AsyncClient, community_id: str, name: Optional[str]) -> None:
    response = await client.post(
        SCHEDULED_POSTS,
        json={
            "text": "Hello",
            "publish_now": True,
            "community": {"id": community_id, "name": name},
        },
    )
    assert response.status_code == 201, response.text


async def _past_communities(client: AsyncClient) -> list[dict]:
    response = await client.get(PAST_COMMUNITIES)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_past_communities_come_most_recently_used_first_each_once(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    await _post_now_into(client, MAKERS, "Indie makers")
    clock.advance(timedelta(minutes=1))
    await _post_now_into(client, WRITERS, "Writers")
    clock.advance(timedelta(minutes=1))
    await _post_now_into(client, MAKERS, "Indie makers")

    assert await _past_communities(client) == [
        {"id": MAKERS, "name": "Indie makers", "url": f"https://x.com/i/communities/{MAKERS}"},
        {"id": WRITERS, "name": "Writers", "url": f"https://x.com/i/communities/{WRITERS}"},
    ]


async def test_a_scheduled_post_counts_as_a_use_too(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    publish_at = "2026-10-11T09:00:00Z"

    response = await client.post(
        SCHEDULED_POSTS,
        json={"text": "Later", "publish_at": publish_at, "community": {"id": MAKERS}},
    )

    assert response.status_code == 201, response.text
    assert [c["id"] for c in await _past_communities(client)] == [MAKERS]


async def test_editing_a_post_into_a_community_counts_as_its_latest_use(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    later = {"text": "Later", "publish_at": "2026-10-11T09:00:00Z"}
    earlier_post = (await client.post(SCHEDULED_POSTS, json=later)).json()
    fixed_clock.advance(timedelta(minutes=1))
    await client.post(SCHEDULED_POSTS, json={**later, "community": {"id": MAKERS}})
    fixed_clock.advance(timedelta(minutes=1))

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{earlier_post['id']}", json={"community": {"id": WRITERS}}
    )

    assert response.status_code == 200, response.text
    assert [c["id"] for c in await _past_communities(client)] == [WRITERS, MAKERS]


async def test_changing_only_the_share_with_followers_choice_is_no_new_use(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    later = {"text": "Later", "publish_at": "2026-10-11T09:00:00Z"}
    makers_post = (
        await client.post(SCHEDULED_POSTS, json={**later, "community": {"id": MAKERS}})
    ).json()
    fixed_clock.advance(timedelta(minutes=1))
    await client.post(SCHEDULED_POSTS, json={**later, "community": {"id": WRITERS}})
    fixed_clock.advance(timedelta(minutes=1))

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{makers_post['id']}", json={"share_with_followers": True}
    )

    assert response.status_code == 200, response.text
    assert [c["id"] for c in await _past_communities(client)] == [WRITERS, MAKERS]


async def test_a_past_community_shows_the_latest_name_stored_for_it(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    await _post_now_into(client, MAKERS, "Makers")
    clock.advance(timedelta(minutes=1))
    await _post_now_into(client, MAKERS, "Indie makers")
    clock.advance(timedelta(minutes=1))
    await _post_now_into(client, MAKERS, None)

    assert [c["name"] for c in await _past_communities(client)] == ["Indie makers"]


async def test_a_past_community_never_named_has_no_name(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    await _post_now_into(client, MAKERS, None)

    assert [c["name"] for c in await _past_communities(client)] == [None]


async def test_profile_posts_add_no_past_community(client, subscribed, fake_x_publisher, clock):
    await _connect_x(client)
    await client.post(SCHEDULED_POSTS, json={"text": "Hello", "publish_now": True})

    assert await _past_communities(client) == []


async def test_only_the_connected_x_account_s_communities_are_offered(
    client, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    await _post_now_into(client, MAKERS, "Indie makers")
    fake_x_publisher.account = XAccount(user_id="2002", handle="grace", subscription_type="None")
    await _connect_x(client)
    await _post_now_into(client, WRITERS, "Writers")

    assert [c["id"] for c in await _past_communities(client)] == [WRITERS]


async def test_without_an_x_connection_no_past_community_is_offered(client, subscribed):
    assert await _past_communities(client) == []
