"""
Retrying a Failed Post with one of its Versions: an edit with `source_version_id` replaces the
Parts not live with that Version's text, and `publish_now` posts it at once (ADR 0014, 0015).
"""

from datetime import timedelta

from httpx import AsyncClient

from pumpkit.posts.models import VersionAttempt
from pumpkit.scheduling.publisher import run_pass
from pumpkit.x_connection.x_publisher import XPostRejectedError

SCHEDULED_POSTS = "/api/v1/scheduled-posts"


async def _failed(client: AsyncClient, fake_x_publisher, version_id: str, *, on_part: int = 1):
    """Post now the Version, with X refusing Part `on_part`, so it comes back Failed."""
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = on_part
    response = await client.post(
        SCHEDULED_POSTS, json={"source_version_id": version_id, "publish_now": True}
    )
    assert response.json()["state"] == "failed", response.text
    fake_x_publisher.fail_publish = None
    fake_x_publisher.fail_publish_on = None
    return response.json()


async def _post_of(client: AsyncClient, db, version_id: str) -> dict:
    version = await db.get(VersionAttempt, version_id)
    return (await client.get(f"/api/v1/posts/{version.post_id}")).json()


async def test_rescheduling_a_failed_post_with_its_latest_version_schedules_that_text(
    client,
    db,
    db_session_maker,
    subscribed,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    version_of,
    next_version,
):
    await connect_x()
    first = await version_of("Refused.")
    failed = await _failed(client, fake_x_publisher, first)
    latest = await next_version(first, "Accepted.")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"source_version_id": latest, "publish_at": "2026-10-10T13:00:00Z"},
    )

    assert response.status_code == 200, response.text
    rescheduled = response.json()
    assert rescheduled["state"] == "scheduled"
    assert rescheduled["source_version_id"] == latest
    assert rescheduled["parts"] == [{"text": "Accepted.", "live": False, "x_post_url": None}]
    assert (await _post_of(client, db, latest))["status"] == "scheduled"
    fixed_clock.advance(timedelta(hours=1))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    assert [text for _, text in fake_x_publisher.published[1:]] == ["Accepted."]


async def test_posting_a_failed_post_now_with_its_latest_version_publishes_it(
    client, db, subscribed, fake_x_publisher, fixed_clock, connect_x, version_of, next_version
):
    await connect_x()
    first = await version_of("Refused.")
    failed = await _failed(client, fake_x_publisher, first)
    latest = await next_version(first, "Accepted.")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"source_version_id": latest, "publish_now": True},
    )

    assert response.status_code == 200, response.text
    published = response.json()
    assert published["state"] == "published"
    assert published["source_version_id"] == latest
    assert published["failed_reason"] is None
    assert [text for _, text in fake_x_publisher.published[1:]] == ["Accepted."]
    assert (await _post_of(client, db, latest))["status"] == "published"


async def test_a_thread_failed_partway_posts_only_the_versions_parts_after_the_live_ones(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, version_of, next_version
):
    await connect_x()
    first = await version_of("Live one.", "Refused two.")
    failed = await _failed(client, fake_x_publisher, first, on_part=2)
    latest = await next_version(first, "Rewritten one.", "Fixed two.", "New three.")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"source_version_id": latest, "publish_now": True},
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


async def test_a_version_with_no_part_after_the_live_ones_is_refused(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, version_of, next_version
):
    await connect_x()
    first = await version_of("Live one.", "Refused two.")
    failed = await _failed(client, fake_x_publisher, first, on_part=2)
    single = await next_version(first, "Just one now.")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"source_version_id": single, "publish_now": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Keep at least one Part after the ones already on X."
    assert len(fake_x_publisher.published) == 2


async def test_a_version_of_another_post_is_refused(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, version_of
):
    await connect_x()
    failed = await _failed(client, fake_x_publisher, await version_of("Refused."))
    elsewhere = await version_of("Another Post.")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"source_version_id": elsewhere, "publish_now": True},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Choose a Version of this Post."
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == [failed]


async def test_a_version_that_is_not_the_users_is_not_found(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, version_of
):
    await connect_x()
    failed = await _failed(client, fake_x_publisher, await version_of("Refused."))

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"source_version_id": "version_attempt_missing", "publish_at": "2026-10-10T14:00:00Z"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Version not found."


async def test_parts_and_a_version_together_are_refused(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, version_of
):
    await connect_x()
    first = await version_of("Refused.")
    failed = await _failed(client, fake_x_publisher, first)

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"source_version_id": first, "parts": ["Typed."], "publish_now": True},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Give either the Parts or a Version, not both."
    assert (await client.get(SCHEDULED_POSTS)).json()["data"] == [failed]


async def test_a_publish_time_and_publish_now_together_are_refused(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, version_of
):
    await connect_x()
    failed = await _failed(client, fake_x_publisher, await version_of("Refused."))

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"publish_at": "2026-10-10T14:00:00Z", "publish_now": True},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Give either a publish time or publish now, not both."
    assert len(fake_x_publisher.published) == 1
