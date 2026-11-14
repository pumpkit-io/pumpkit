"""
Reading a Brief through `GET /briefs/{id}`: each written Post carries the status its Scheduled post
gives it (ADR 0015), so the Brief's page can show a badge in place of "Post to…".
"""

import asyncio

import pytest
from sqlalchemy import update

from pumpkit.scheduling.models import PUBLISHED, PUBLISHING, ScheduledPost
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import SKETCHED_POST, started_post_id

BRIEFS = "/api/v1/briefs"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
LATER = "2026-10-10T14:00:00Z"


@pytest.fixture
async def written(client, subscribed, connect_x, fake_llm, fixed_clock) -> dict:
    """A Brief with one Idea, its Post written: the Brief as its page first reads it."""
    await connect_x()
    await save_positioning(client)
    fake_llm.replies = [{"post": "Version one."}]
    planned = await client.post(BRIEFS, json={"brief": "ship small things"})
    assert planned.status_code == 201, planned.text
    assert started_post_id(planned)
    return planned.json()


async def _post_of(client, brief: dict) -> dict:
    response = await client.get(f"{BRIEFS}/{brief['id']}")
    assert response.status_code == 200, response.text
    [idea] = response.json()["ideas"]
    return idea["post"]


async def test_a_written_post_reads_as_a_draft(client, written):
    post = await _post_of(client, written)

    assert post["status"] == "draft"
    assert post["publishing"] is False


async def test_a_post_being_written_has_no_status(
    client, subscribed, fake_llm, fixed_clock, background_tasks
):
    await save_positioning(client)
    held = asyncio.Event()
    fake_llm.held[SKETCHED_POST] = held
    planned = await client.post(BRIEFS, json={"brief": "ship small things"})

    post = await _post_of(client, planned.json())

    assert post["writing_state"] == "writing"
    assert post["status"] is None
    held.set()
    await background_tasks.wait()


async def test_a_scheduled_post_reads_as_scheduled(client, written):
    post = await _post_of(client, written)
    scheduled = await client.post(
        SCHEDULED_POSTS, json={"post_id": post["id"], "publish_at": LATER}
    )
    assert scheduled.status_code == 201, scheduled.text

    assert (await _post_of(client, written))["status"] == "scheduled"


async def test_a_published_post_reads_as_published(client, db, written):
    post = await _post_of(client, written)
    scheduled = await client.post(
        SCHEDULED_POSTS, json={"post_id": post["id"], "publish_at": LATER}
    )
    assert scheduled.status_code == 201, scheduled.text
    await db.execute(
        update(ScheduledPost)
        .where(ScheduledPost.id == scheduled.json()["id"])
        .values(state=PUBLISHED)
    )
    await db.commit()

    assert (await _post_of(client, written))["status"] == "published"


async def test_a_post_being_published_reads_as_scheduled_and_publishing(client, db, written):
    post = await _post_of(client, written)
    scheduled = await client.post(
        SCHEDULED_POSTS, json={"post_id": post["id"], "publish_at": LATER}
    )
    assert scheduled.status_code == 201, scheduled.text
    await db.execute(
        update(ScheduledPost)
        .where(ScheduledPost.id == scheduled.json()["id"])
        .values(state=PUBLISHING)
    )
    await db.commit()

    post = await _post_of(client, written)
    assert post["status"] == "scheduled"
    assert post["publishing"] is True
