"""
The publishing module as the publisher will call it: for a Scheduled post it didn't just
create, in a session of its own. Outcomes are checked through the HTTP API.
"""

from urllib.parse import parse_qs, urlsplit

from httpx import AsyncClient

import app.api.services.scheduled_posts as scheduled_posts_service
from app.core.x_publisher import XAccount
from app.publishing.publish import publish_scheduled_post

SCHEDULED_POSTS = "/api/v1/scheduled-posts"


async def _connect_x(client: AsyncClient) -> None:
    started = await client.post("/api/v1/x-connection/authorizations")
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
    completed = await client.post(
        "/api/v1/x-connection/authorizations/complete", json={"code": "c", "state": state}
    )
    assert completed.status_code == 200, completed.text


async def _waiting(db, user, clock, x_user_id: str = "1001") -> str:
    """A Scheduled post in scheduled, due now, as the publisher would find it."""
    now = clock()
    scheduled_post = await scheduled_posts_service.create(
        db,
        user_id=user.id,
        x_user_id=x_user_id,
        text="Due now",
        publish_at=now.replace(second=0, microsecond=0),
        now=now,
    )
    await db.commit()
    return scheduled_post.id


async def _publish(db_session_maker, fake_x_publisher, scheduled_post_id: str, clock) -> bool:
    async with db_session_maker() as session:
        return await publish_scheduled_post(
            session, fake_x_publisher, scheduled_post_id=scheduled_post_id, now=clock()
        )


async def test_a_waiting_scheduled_post_is_published(
    client, db, db_session_maker, user, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    scheduled_post_id = await _waiting(db, user, clock)

    assert await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    [listed] = (await client.get(SCHEDULED_POSTS)).json()["data"]
    assert listed["id"] == scheduled_post_id
    assert listed["state"] == "published"
    assert fake_x_publisher.published == [("access-1001-1", "Due now")]


async def test_x_is_called_at_most_once_per_scheduled_post(
    client, db, db_session_maker, user, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    scheduled_post_id = await _waiting(db, user, clock)
    await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    published_again = await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    assert published_again is False
    assert len(fake_x_publisher.published) == 1


async def test_a_user_who_is_no_longer_subscribed_gets_a_failed_post_and_nothing_on_x(
    client, db, db_session_maker, user, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    scheduled_post_id = await _waiting(db, user, clock)
    subscribed.status = "canceled"
    await db.commit()

    await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    [listed] = (await client.get(SCHEDULED_POSTS)).json()["data"]
    assert listed["state"] == "failed"
    assert listed["failed_reason"] == (
        "Not published: your Subscription had ended. Subscribe, then reschedule it."
    )
    assert fake_x_publisher.published == []


async def test_a_post_for_another_x_account_fails_instead_of_going_out_on_the_new_one(
    client, db, db_session_maker, user, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    scheduled_post_id = await _waiting(db, user, clock)
    fake_x_publisher.account = XAccount(user_id="2002", handle="grace", subscription_type="None")
    await _connect_x(client)

    await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    [listed] = (await client.get(SCHEDULED_POSTS)).json()["data"]
    assert listed["state"] == "failed"
    assert listed["failed_reason"] == (
        "Not published: the X account it was for is no longer connected to Pumpkit."
    )
    assert fake_x_publisher.published == []


async def test_a_post_whose_x_connection_is_gone_fails(
    client, db, db_session_maker, user, subscribed, fake_x_publisher, clock
):
    await _connect_x(client)
    scheduled_post_id = await _waiting(db, user, clock)
    assert (await client.delete("/api/v1/x-connection")).status_code == 204

    await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    [listed] = (await client.get(SCHEDULED_POSTS)).json()["data"]
    assert listed["state"] == "failed"
    assert fake_x_publisher.published == []
