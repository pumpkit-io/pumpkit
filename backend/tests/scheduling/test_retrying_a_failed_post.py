"""
Retrying a Failed Post with its Text: an edit with `copy_text` replaces the Parts not live with
the Post's Text, and `publish_now` posts it at once (ADR 0014, 0016).
"""

from datetime import timedelta

from httpx import AsyncClient

from pumpkit.scheduling.publisher import run_pass
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.scheduling.reading import scheduled_posts

SCHEDULED_POSTS = "/api/v1/scheduled-posts"


async def _failed(client: AsyncClient, fake_x_publisher, post_id: str, *, on_part: int = 1):
    """Post now the Post's Text, with X refusing Part `on_part`, so it comes back Failed."""
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = on_part
    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert response.json()["state"] == "failed", response.text
    fake_x_publisher.fail_publish = None
    fake_x_publisher.fail_publish_on = None
    return response.json()


async def _status_of(client: AsyncClient, post_id: str) -> str:
    return (await client.get(f"/api/v1/posts/{post_id}")).json()["status"]


async def test_rescheduling_a_failed_post_with_its_text_schedules_that_text(
    client,
    db_session_maker,
    subscribed,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
    next_version,
):
    await connect_x()
    post_id = await post_with("Refused.")
    failed = await _failed(client, fake_x_publisher, post_id)
    await next_version(post_id, "Accepted.")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"copy_text": True, "publish_at": "2026-10-10T13:00:00Z"},
    )

    assert response.status_code == 200, response.text
    rescheduled = response.json()
    assert rescheduled["state"] == "scheduled"
    assert rescheduled["parts"] == [{"text": "Accepted.", "live": False, "x_post_url": None}]
    assert await _status_of(client, post_id) == "scheduled"
    fixed_clock.advance(timedelta(hours=1))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    assert [text for _, text in fake_x_publisher.published[1:]] == ["Accepted."]


async def test_posting_a_failed_post_now_with_its_text_publishes_it(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with, next_version
):
    await connect_x()
    post_id = await post_with("Refused.")
    failed = await _failed(client, fake_x_publisher, post_id)
    await next_version(post_id, "Accepted.")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}", json={"copy_text": True, "publish_now": True}
    )

    assert response.status_code == 200, response.text
    published = response.json()
    assert published["state"] == "published"
    assert published["failed_reason"] is None
    assert [text for _, text in fake_x_publisher.published[1:]] == ["Accepted."]
    assert await _status_of(client, post_id) == "published"


async def test_a_thread_failed_partway_keeps_its_live_parts_and_posts_the_texts_after_them(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with, next_version
):
    await connect_x()
    post_id = await post_with("Live one.", "Refused two.")
    failed = await _failed(client, fake_x_publisher, post_id, on_part=2)
    await next_version(post_id, "Rewritten one.", "Fixed two.", "New three.")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}", json={"copy_text": True, "publish_now": True}
    )

    assert response.status_code == 200, response.text
    published = response.json()
    assert published["state"] == "published"
    assert [part["text"] for part in published["parts"]] == [
        "Live one.",
        "Fixed two.",
        "New three.",
    ]
    assert published["parts"][0] == failed["parts"][0]
    assert [text for _, text in fake_x_publisher.published[2:]] == ["Fixed two.", "New three."]
    assert fake_x_publisher.replied_to[2:] == ["1890000000000000001", "1890000000000000003"]


async def test_a_text_with_no_part_after_the_live_ones_is_refused(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with, next_version
):
    await connect_x()
    post_id = await post_with("Live one.", "Refused two.")
    failed = await _failed(client, fake_x_publisher, post_id, on_part=2)
    await next_version(post_id, "Just one now.")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}", json={"copy_text": True, "publish_now": True}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Keep at least one Part after the ones already on X."
    assert len(fake_x_publisher.published) == 2


async def test_a_source_version_is_no_longer_taken(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    failed = await _failed(client, fake_x_publisher, await post_with("Refused."))

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"source_version_id": "version_attempt_any", "publish_now": True},
    )

    assert response.status_code == 422
    assert await scheduled_posts(client) == [failed]


async def test_parts_and_the_text_together_are_refused(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    failed = await _failed(client, fake_x_publisher, await post_with("Refused."))

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"copy_text": True, "parts": ["Typed."], "publish_now": True},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Give either the Parts or the Post's Text, not both."
    assert await scheduled_posts(client) == [failed]


async def test_a_publish_time_and_publish_now_together_are_refused(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    failed = await _failed(client, fake_x_publisher, await post_with("Refused."))

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"publish_at": "2026-10-10T14:00:00Z", "publish_now": True},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Give either a publish time or publish now, not both."
    assert len(fake_x_publisher.published) == 1
