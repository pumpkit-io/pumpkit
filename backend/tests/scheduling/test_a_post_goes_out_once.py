"""
ADR 0015 through the HTTP API: every Scheduled post is copied from its Post's Text, a Post has at
most one, and a Scheduled or Published Post takes no Feedback.
"""

import asyncio
from datetime import timedelta

import pytest

from pumpkit.scheduling import service
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.positioning.positioning import save_positioning
from tests.posts.feedback import latest_version
from tests.posts.writing_replies import REVISED_POST, started_post_id
from tests.scheduling.reading import scheduled_posts

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
LATER = "2026-10-10T14:00:00Z"
ALREADY_SCHEDULED = "This post already has a scheduled post. Edit it, or unschedule it first."
SCHEDULED_TAKES_NO_FEEDBACK = (
    "This post is scheduled, so it takes no feedback. Edit its text, or unschedule it first."
)
PUBLISHED_TAKES_NO_FEEDBACK = (
    "This post is published, so it takes no feedback. Start a new post to write another."
)


@pytest.fixture
async def post(client, subscribed, fake_x_reader, fake_llm, fixed_clock, connect_x) -> dict:
    """A Post written through the API, with one Version, and the User's X account connected."""
    await connect_x()
    await save_positioning(client)
    fake_llm.replies = [{"post": "Version one."}]
    started = await client.post("/api/v1/briefs", json={"brief": "ship small things"})
    assert started.status_code == 201, started.text
    return (await client.get(f"/api/v1/posts/{started_post_id(started)}")).json()


async def _give_feedback(client, fake_llm, post: dict, feedback: str = "punchier"):
    fake_llm.replies = [{"post": f"Version after {feedback}."}]
    return await client.post(f"/api/v1/posts/{post['id']}/versions", json={"feedback": feedback})


async def test_creating_a_scheduled_post_without_a_post_is_refused(
    client, subscribed, fixed_clock, connect_x
):
    await connect_x()

    response = await client.post(SCHEDULED_POSTS, json={"publish_at": LATER})

    assert response.status_code == 422
    assert (await scheduled_posts(client)) == []


async def test_typed_parts_are_refused_on_creation(client, post):
    response = await client.post(
        SCHEDULED_POSTS,
        json={"parts": ["Typed."], "post_id": post["id"], "publish_at": LATER},
    )

    assert response.status_code == 422
    assert (await scheduled_posts(client)) == []


async def test_a_second_scheduled_post_for_the_same_post_is_refused(client, fake_llm, post):
    first = await client.post(SCHEDULED_POSTS, json={"post_id": post["id"], "publish_at": LATER})
    assert first.status_code == 201, first.text

    again = await client.post(SCHEDULED_POSTS, json={"post_id": post["id"], "publish_now": True})

    assert again.status_code == 409
    assert again.json()["detail"] == ALREADY_SCHEDULED
    assert [s["id"] for s in (await scheduled_posts(client))] == [first.json()["id"]]


async def test_a_published_post_cannot_be_scheduled_again(client, fake_x_publisher, post):
    published = await client.post(
        SCHEDULED_POSTS, json={"post_id": post["id"], "publish_now": True}
    )
    assert published.json()["state"] == "published"

    again = await client.post(SCHEDULED_POSTS, json={"post_id": post["id"], "publish_at": LATER})

    assert again.status_code == 409
    assert again.json()["detail"] == ALREADY_SCHEDULED
    assert len(fake_x_publisher.published) == 1


async def test_a_failed_post_cannot_be_scheduled_again_until_its_scheduled_post_is_deleted(
    client, fake_x_publisher, post
):
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Nope")
    failed = await client.post(SCHEDULED_POSTS, json={"post_id": post["id"], "publish_now": True})
    assert failed.json()["state"] == "failed"
    fake_x_publisher.fail_publish = None

    refused = await client.post(SCHEDULED_POSTS, json={"post_id": post["id"], "publish_at": LATER})
    deleted = await client.delete(f"{SCHEDULED_POSTS}/{failed.json()['id']}")
    again = await client.post(SCHEDULED_POSTS, json={"post_id": post["id"], "publish_at": LATER})

    assert refused.status_code == 409
    assert refused.json()["detail"] == ALREADY_SCHEDULED
    assert deleted.status_code == 204
    assert again.status_code == 201, again.text


async def test_feedback_on_a_draft_writes_the_next_version(client, fake_llm, post):
    response = await _give_feedback(client, fake_llm, post)

    assert response.status_code == 202, response.text
    assert (await latest_version(client, post["id"]))["number"] == 2


async def test_feedback_on_a_scheduled_post_is_refused_naming_the_fix(client, fake_llm, post):
    await client.post(SCHEDULED_POSTS, json={"post_id": post["id"], "publish_at": LATER})

    response = await _give_feedback(client, fake_llm, post)

    assert response.status_code == 409
    assert response.json()["detail"] == SCHEDULED_TAKES_NO_FEEDBACK
    assert fake_llm.replies, "no model was called"


async def test_feedback_on_a_post_being_published_is_refused_as_scheduled(
    client, db_session_maker, fake_llm, fixed_clock, post
):
    scheduled = await client.post(
        SCHEDULED_POSTS,
        json={"post_id": post["id"], "publish_at": "2026-10-10T12:02:00Z"},
    )
    async with db_session_maker() as session:
        fixed_clock.advance(timedelta(minutes=2))
        assert await service.claim(
            session, scheduled_post_id=scheduled.json()["id"], now=fixed_clock()
        )
        await session.commit()

    response = await _give_feedback(client, fake_llm, post)

    assert response.status_code == 409
    assert response.json()["detail"] == SCHEDULED_TAKES_NO_FEEDBACK


async def test_feedback_on_a_published_post_is_refused_naming_the_fix(client, fake_llm, post):
    await client.post(SCHEDULED_POSTS, json={"post_id": post["id"], "publish_now": True})

    response = await _give_feedback(client, fake_llm, post)

    assert response.status_code == 409
    assert response.json()["detail"] == PUBLISHED_TAKES_NO_FEEDBACK


async def test_feedback_on_a_failed_post_writes_the_next_version(
    client, fake_llm, fake_x_publisher, post
):
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Nope")
    failed = await client.post(SCHEDULED_POSTS, json={"post_id": post["id"], "publish_now": True})
    assert failed.json()["state"] == "failed"

    response = await _give_feedback(client, fake_llm, post)

    assert response.status_code == 202, response.text
    assert (await latest_version(client, post["id"]))["number"] == 2


async def test_unscheduling_makes_the_post_a_draft_again(client, fake_llm, post):
    scheduled = await client.post(
        SCHEDULED_POSTS, json={"post_id": post["id"], "publish_at": LATER}
    )

    deleted = await client.delete(f"{SCHEDULED_POSTS}/{scheduled.json()['id']}")
    feedback = await _give_feedback(client, fake_llm, post)
    again = await client.post(
        SCHEDULED_POSTS,
        json={"post_id": post["id"], "publish_at": LATER},
    )

    assert deleted.status_code == 204
    assert feedback.status_code == 202, feedback.text
    assert again.status_code == 201, again.text
    assert again.json()["parts"][0]["text"] == "Version after punchier."


async def test_feedback_on_someone_else_s_post_is_not_found(client, subscribed, fake_llm):
    response = await client.post(
        "/api/v1/posts/post_01M4JS3D7BER5QZANNA2D0EFRQ/versions", json={"feedback": "punchier"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Post not found."


BEING_WRITTEN = "Pumpkit is writing a new version of this post. Try again once it's written."


@pytest.fixture
def revising(fake_llm) -> asyncio.Event:
    """Holds every revise call until the test sets the event, so a Feedback stays in flight."""
    event = asyncio.Event()
    fake_llm.held[REVISED_POST] = event
    return event


@pytest.mark.parametrize(
    "when", [{"publish_at": LATER}, {"publish_now": True}], ids=["schedule", "post now"]
)
async def test_a_post_whose_feedback_is_being_written_cannot_be_scheduled(
    post, client, fake_llm, fake_x_publisher, background_tasks, revising, when
):
    feedback = await _give_feedback(client, fake_llm, post)
    assert feedback.status_code == 202, feedback.text

    response = await client.post(SCHEDULED_POSTS, json={"post_id": post["id"], **when})

    assert response.status_code == 409
    assert response.json()["detail"] == BEING_WRITTEN
    assert fake_x_publisher.published == []
    revising.set()
    await background_tasks.wait()
    assert (await latest_version(client, post["id"]))["number"] == 2


@pytest.mark.parametrize(
    "edit", [{"publish_now": True}, {"copy_text": True}], ids=["post now", "copy the text"]
)
async def test_a_failed_post_whose_feedback_is_being_written_cannot_be_rescheduled_or_copied(
    post, client, fake_llm, fake_x_publisher, background_tasks, revising, edit
):
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Nope")
    failed = await client.post(SCHEDULED_POSTS, json={"post_id": post["id"], "publish_now": True})
    assert failed.json()["state"] == "failed"
    fake_x_publisher.fail_publish = None
    assert (await _give_feedback(client, fake_llm, post)).status_code == 202

    response = await client.patch(f"{SCHEDULED_POSTS}/{failed.json()['id']}", json=edit)

    assert response.status_code == 409
    assert response.json()["detail"] == BEING_WRITTEN
    revising.set()
    await background_tasks.wait()
    assert (await latest_version(client, post["id"]))["number"] == 2
