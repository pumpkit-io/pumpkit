"""
Publishing as the publisher will call it: for a Scheduled post it didn't just
create, in a session of its own. Outcomes are checked through the HTTP API.
"""

import pumpkit.scheduling.service as scheduled_posts_service
from pumpkit.scheduling.publishing import publish_scheduled_post
from pumpkit.x_connection.x_publisher import XAccount
from tests.scheduling.reading import scheduled_posts

SCHEDULED_POSTS = "/api/v1/scheduled-posts"


async def _waiting(
    db,
    user,
    clock,
    post_with,
    x_user_id: str = "1001",
    parts: tuple[str, ...] = ("Due now",),
) -> str:
    """A Scheduled post in scheduled, due now, as the publisher would find it."""
    now = clock()
    scheduled_post = await scheduled_posts_service.create(
        db,
        user_id=user.id,
        post_id=await post_with(*parts),
        x_user_id=x_user_id,
        parts=list(parts),
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
    post_with, client, db, db_session_maker, user, subscribed, fake_x_publisher, clock, connect_x
):
    await connect_x()
    scheduled_post_id = await _waiting(db, user, clock, post_with)

    assert await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    [listed] = await scheduled_posts(client)
    assert listed["id"] == scheduled_post_id
    assert listed["state"] == "published"
    assert fake_x_publisher.published == [("access-1001-1", "Due now")]


async def test_x_is_called_at_most_once_per_scheduled_post(
    post_with, client, db, db_session_maker, user, subscribed, fake_x_publisher, clock, connect_x
):
    await connect_x()
    scheduled_post_id = await _waiting(db, user, clock, post_with)
    await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    published_again = await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    assert published_again is False
    assert len(fake_x_publisher.published) == 1


async def test_x_is_called_at_most_once_per_part_of_a_thread(
    post_with, client, db, db_session_maker, user, subscribed, fake_x_publisher, clock, connect_x
):
    await connect_x()
    scheduled_post_id = await _waiting(db, user, clock, post_with, parts=("One", "Two", "Three"))
    await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    published_again = await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    assert published_again is False
    assert [text for _, text in fake_x_publisher.published] == ["One", "Two", "Three"]


async def test_a_user_who_is_no_longer_subscribed_gets_a_failed_post_and_nothing_on_x(
    post_with, client, db, db_session_maker, user, subscribed, fake_x_publisher, clock, connect_x
):
    await connect_x()
    scheduled_post_id = await _waiting(db, user, clock, post_with)
    subscribed.status = "canceled"
    await db.commit()

    await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    subscribed.status = "active"
    await db.commit()
    [listed] = await scheduled_posts(client)
    assert listed["state"] == "failed"
    assert listed["failed_reason"] == (
        "Not published: your subscription had ended. Subscribe, then reschedule it."
    )
    assert fake_x_publisher.published == []


async def test_a_post_for_another_x_account_fails_instead_of_going_out_on_the_new_one(
    post_with, client, db, db_session_maker, user, subscribed, fake_x_publisher, clock, connect_x
):
    await connect_x()
    scheduled_post_id = await _waiting(db, user, clock, post_with)
    fake_x_publisher.account = XAccount(user_id="2002", handle="grace", subscription_type="None")
    await connect_x()

    await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    [listed] = await scheduled_posts(client)
    assert listed["state"] == "failed"
    assert listed["failed_reason"] == (
        "Not published: the X account it was for is no longer connected to Pumpkit."
    )
    assert fake_x_publisher.published == []


async def test_a_post_whose_x_connection_is_gone_fails(
    post_with, client, db, db_session_maker, user, subscribed, fake_x_publisher, clock, connect_x
):
    await connect_x()
    scheduled_post_id = await _waiting(db, user, clock, post_with)
    assert (await client.delete("/api/v1/x-connection")).status_code == 204

    await _publish(db_session_maker, fake_x_publisher, scheduled_post_id, clock)

    [listed] = await scheduled_posts(client)
    assert listed["state"] == "failed"
    assert fake_x_publisher.published == []
