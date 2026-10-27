"""Changing the Community of a Scheduled post, and its share with followers, with the frozen clock."""

from datetime import timedelta

import pytest
from httpx import AsyncClient

import pumpkit.scheduling.service as scheduled_posts_service
from pumpkit.scheduling.publisher import run_pass
from pumpkit.x_connection.x_publisher import XPostRejectedError

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
PUBLISHING_STARTED = "Publishing has started, so this Scheduled post can no longer change."
COMMUNITY_ID = "1493446837214187523"
COMMUNITY_URL = f"https://x.com/i/communities/{COMMUNITY_ID}"


@pytest.fixture(autouse=True)
def known_communities(fake_x_reader) -> None:
    fake_x_reader.communities.update({COMMUNITY_ID: "Indie makers", "42": "Other"})


async def _schedule(
    client: AsyncClient, publish_at: str = "2026-10-10T14:00:00Z", **destination
) -> dict:
    response = await client.post(
        SCHEDULED_POSTS, json={"parts": ["Later today."], "publish_at": publish_at, **destination}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _listed(client: AsyncClient) -> list[dict]:
    return (await client.get(SCHEDULED_POSTS)).json()["data"]


async def test_a_scheduled_post_moves_from_the_profile_into_a_community(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    scheduled = await _schedule(client)

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}",
        json={
            "community": COMMUNITY_ID,
            "share_with_followers": True,
        },
    )

    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited == {
        **scheduled,
        "community": {"id": COMMUNITY_ID, "name": "Indie makers", "url": COMMUNITY_URL},
        "share_with_followers": True,
    }
    assert await _listed(client) == [edited]


async def test_clearing_the_community_moves_it_back_to_the_profile_without_sharing(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    scheduled = await _schedule(client, community=COMMUNITY_ID, share_with_followers=True)

    response = await client.patch(f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"community": None})

    assert response.status_code == 200, response.text
    assert response.json() == {**scheduled, "community": None, "share_with_followers": False}


async def test_share_with_followers_changes_on_its_own_and_keeps_the_community(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    scheduled = await _schedule(client, community=COMMUNITY_ID, share_with_followers=True)

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"share_with_followers": False}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {**scheduled, "share_with_followers": False}


async def test_another_community_keeps_the_share_with_followers_choice_unless_given(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    scheduled = await _schedule(client, community=COMMUNITY_ID, share_with_followers=True)

    response = await client.patch(f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"community": "42"})

    assert response.status_code == 200, response.text
    assert response.json() == {
        **scheduled,
        "community": {"id": "42", "name": "Other", "url": "https://x.com/i/communities/42"},
    }


@pytest.mark.parametrize(
    "change", [{"share_with_followers": None}, {"community": {"id": COMMUNITY_ID, "x": 1}}]
)
async def test_an_edit_needs_something_to_change(
    client, subscribed, fake_x_publisher, fixed_clock, change, connect_x
):
    await connect_x()
    scheduled = await _schedule(client)

    response = await client.patch(f"{SCHEDULED_POSTS}/{scheduled['id']}", json=change)

    assert response.status_code == 422
    assert await _listed(client) == [scheduled]


async def test_a_failed_post_moves_into_a_community_and_is_rescheduled_there(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    scheduled = await _schedule(client, publish_at="2026-10-10T12:02:00Z")
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Forbidden.")
    fixed_clock.advance(timedelta(minutes=2))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    assert (await _listed(client))[0]["state"] == "failed"
    fake_x_publisher.fail_publish = None

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}",
        json={
            "community": COMMUNITY_ID,
            "share_with_followers": False,
            "publish_at": "2026-10-10T12:05:00Z",
        },
    )
    fixed_clock.advance(timedelta(minutes=3))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert response.status_code == 200, response.text
    assert (await _listed(client))[0]["state"] == "published"
    assert fake_x_publisher.published_to[-1] == (COMMUNITY_ID, False)


async def test_a_failed_post_s_community_changes_without_rescheduling_it(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    scheduled = await _schedule(client, publish_at="2026-10-10T12:02:00Z", community=COMMUNITY_ID)
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Forbidden.")
    fixed_clock.advance(timedelta(minutes=2))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    failed = (await _listed(client))[0]

    response = await client.patch(f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"community": None})

    assert response.status_code == 200, response.text
    assert failed["state"] == "failed"
    assert response.json() == {**failed, "community": None}


async def test_a_publishing_scheduled_post_s_community_cannot_change(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x
):
    await connect_x()
    scheduled = await _schedule(client, publish_at="2026-10-10T12:02:00Z")
    fixed_clock.advance(timedelta(minutes=2))
    async with db_session_maker() as session:
        assert await scheduled_posts_service.claim(
            session, scheduled_post_id=scheduled["id"], now=fixed_clock()
        )
        await session.commit()

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}",
        json={"community": COMMUNITY_ID},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == PUBLISHING_STARTED
    assert (await _listed(client))[0]["community"] is None


@pytest.mark.parametrize("change", [{"community": None}, {"share_with_followers": False}])
async def test_a_published_scheduled_post_s_community_cannot_change(
    client, subscribed, fake_x_publisher, fixed_clock, change, connect_x
):
    await connect_x()
    published = (
        await client.post(
            SCHEDULED_POSTS,
            json={
                "parts": ["Out"],
                "publish_now": True,
                "community": COMMUNITY_ID,
                "share_with_followers": True,
            },
        )
    ).json()

    response = await client.patch(f"{SCHEDULED_POSTS}/{published['id']}", json=change)

    assert response.status_code == 409
    assert response.json()["detail"] == PUBLISHING_STARTED
    assert await _listed(client) == [published]
