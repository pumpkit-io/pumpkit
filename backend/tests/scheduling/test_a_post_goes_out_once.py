"""
ADR 0015 through the HTTP API: every Scheduled post is copied from its Post's Text, a Post has at
most one, and a Scheduled or Published Post takes no Feedback.
"""

from datetime import datetime, timedelta, timezone

import pytest

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.main import app
from pumpkit.posts.llm import FakeLLM, get_llm
from pumpkit.scheduling import service
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.posts.writing_replies import written
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
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    added = await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    assert added.status_code == 201, added.text
    fake_llm.replies = [written("sketch one"), {"post": "Version one."}]
    started = await client.post("/api/v1/posts", json={"brief": "ship small things"})
    assert started.status_code == 201, started.text
    return started.json()


async def _give_feedback(client, fake_llm, post: dict, feedback: str = "punchier"):
    fake_llm.replies = [written("sketch next"), {"post": f"Version after {feedback}."}]
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

    assert response.status_code == 201, response.text
    assert response.json()["number"] == 2


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

    assert response.status_code == 201, response.text
    assert response.json()["number"] == 2


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
    assert feedback.status_code == 201, feedback.text
    assert again.status_code == 201, again.text
    assert again.json()["parts"][0]["text"] == "Version after punchier."


async def test_feedback_on_someone_else_s_post_is_not_found(client, subscribed, fake_llm):
    response = await client.post(
        "/api/v1/posts/post_01M4JS3D7BER5QZANNA2D0EFRQ/versions", json={"feedback": "punchier"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Post not found."


async def test_a_post_scheduled_while_its_feedback_version_is_written_does_not_take_it(
    client, fake_llm, post
):
    scheduled_mid_write = []

    class SchedulingLLM(FakeLLM):
        async def structured(self, **kwargs):
            if not scheduled_mid_write:
                scheduled_mid_write.append(
                    await client.post(
                        SCHEDULED_POSTS,
                        json={"post_id": post["id"], "publish_at": LATER},
                    )
                )
            return await super().structured(**kwargs)

    llm = SchedulingLLM(replies=[written("sketch next"), {"post": "Version after punchier."}])
    app.dependency_overrides[get_llm] = lambda: llm
    response = await client.post(
        f"/api/v1/posts/{post['id']}/versions", json={"feedback": "punchier"}
    )
    read = await client.get(f"/api/v1/posts/{post['id']}")

    assert scheduled_mid_write[0].status_code == 201, scheduled_mid_write[0].text
    assert response.status_code == 409
    assert response.json()["detail"] == SCHEDULED_TAKES_NO_FEEDBACK
    assert [version["number"] for version in read.json()["versions"]] == [1]
