"""
Reading one Post through `GET /posts/{id}` and the `get_post` tool: its Brief, its Versions, the
status its Scheduled post gives it (ADR 0015), and that Scheduled post.
"""

from datetime import datetime, timedelta, timezone

import pytest

from pumpkit.auth.models import User
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.posts.llm import LLMError
from pumpkit.posts.models import Post
from pumpkit.scheduling import service
from pumpkit.x_connection.x_length import X_POST_MAX_CHARS
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.mcp_client import error_text
from tests.posts.writing_replies import written, written_thread

POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
LATER = "2026-10-10T14:00:00Z"


@pytest.fixture
async def with_author(client, subscribed, fake_x_reader, connect_x) -> None:
    """`levelsio` in the User's Persona, and the User's X account connected."""
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


@pytest.fixture
async def post(client, with_author, fake_llm, fixed_clock) -> dict:
    """A Post written through the API, with one Version."""
    fake_llm.replies = [written("sketch one"), {"post": "Version one."}]
    started = await client.post(POSTS, json={"brief": "ship small things"})
    assert started.status_code == 201, started.text
    return started.json()


async def _schedule(client, post_id: str, **when) -> dict:
    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, **when})
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_draft_reads_with_its_brief_text_versions_and_no_scheduled_post(client, post):
    response = await client.get(f"{POSTS}/{post['id']}")

    assert response.status_code == 200, response.text
    one = {"text": "Version one.", "char_count": 12, "char_limit": X_POST_MAX_CHARS}
    assert response.json() == {
        "id": post["id"],
        "brief": "ship small things",
        "text": {"format": "post", "parts": [one], "version_number": 1, "edited": False},
        "versions": [
            {
                "id": post["versions"][0]["id"],
                "number": 1,
                "feedback": None,
                "format": "post",
                "parts": [one],
                "starting_text": None,
                "created_at": "2026-10-10T12:00:30Z",
            }
        ],
        "status": "draft",
        "scheduled_post": None,
    }


async def test_feedback_makes_the_new_version_the_text(client, post, fake_llm):
    fake_llm.replies = [written_thread(["one", "two"]), {"parts": ["Part one.", "Part two."]}]
    given = await client.post(
        f"{POSTS}/{post['id']}/versions", json={"feedback": "expand it", "format": "thread"}
    )
    assert given.status_code == 201, given.text

    read = (await client.get(f"{POSTS}/{post['id']}")).json()

    assert read["text"] == {
        "format": "thread",
        "parts": [
            {"text": "Part one.", "char_count": 9, "char_limit": X_POST_MAX_CHARS},
            {"text": "Part two.", "char_count": 9, "char_limit": X_POST_MAX_CHARS},
        ],
        "version_number": 2,
        "edited": False,
    }
    assert read["versions"][1]["feedback"] == "expand it"


async def test_a_failed_feedback_leaves_the_text_on_the_version_before(client, post, fake_llm):
    fake_llm.replies = [LLMError("provider down")]
    await client.post(f"{POSTS}/{post['id']}/versions", json={"feedback": "shorter"})

    read = (await client.get(f"{POSTS}/{post['id']}")).json()

    assert read["text"]["version_number"] == 1
    assert [p["text"] for p in read["text"]["parts"]] == ["Version one."]


async def test_a_scheduled_post_reads_as_scheduled_with_its_scheduled_post(client, post):
    scheduled = await _schedule(client, post["id"], publish_at=LATER)

    read = (await client.get(f"{POSTS}/{post['id']}")).json()

    assert (read["status"], read["scheduled_post"]) == ("scheduled", scheduled)


async def test_a_post_being_published_still_reads_as_scheduled(
    client, db_session_maker, fixed_clock, post
):
    scheduled = await _schedule(client, post["id"], publish_at="2026-10-10T12:02:00Z")
    async with db_session_maker() as session:
        fixed_clock.advance(timedelta(minutes=2))
        assert await service.claim(session, scheduled_post_id=scheduled["id"], now=fixed_clock())
        await session.commit()

    read = (await client.get(f"{POSTS}/{post['id']}")).json()

    assert (read["status"], read["scheduled_post"]["state"]) == ("scheduled", "publishing")


async def test_a_published_post_reads_as_published_with_its_link_on_x(client, post):
    published = await _schedule(client, post["id"], publish_now=True)

    read = (await client.get(f"{POSTS}/{post['id']}")).json()

    assert read["status"] == "published"
    assert read["scheduled_post"] == published
    assert read["scheduled_post"]["x_post_url"] == "https://x.com/i/web/status/1890000000000000001"


async def test_a_thread_that_failed_partway_reads_as_failed_with_its_live_part(
    client, with_author, fake_llm, fake_x_publisher
):
    fake_llm.replies = [
        written_thread(["sketch one", "sketch two"]),
        {"parts": ["Live one.", "Refused two."]},
    ]
    post = (await client.post(POSTS, json={"brief": "ship", "format": "thread"})).json()
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Nope")
    fake_x_publisher.fail_publish_on = 2

    failed = await _schedule(client, post["id"], publish_now=True)
    read = (await client.get(f"{POSTS}/{post['id']}")).json()

    assert read["status"] == "failed"
    assert read["scheduled_post"] == failed
    assert [(p["text"], p["live"]) for p in read["scheduled_post"]["parts"]] == [
        ("Live one.", True),
        ("Refused two.", False),
    ]
    assert read["scheduled_post"]["failed_reason"]


async def test_unscheduling_reads_the_post_as_a_draft_again(client, post):
    scheduled = await _schedule(client, post["id"], publish_at=LATER)
    await client.delete(f"{SCHEDULED_POSTS}/{scheduled['id']}")

    read = (await client.get(f"{POSTS}/{post['id']}")).json()

    assert (read["status"], read["scheduled_post"]) == ("draft", None)


@pytest.fixture
async def bobs_post_id(db, fixed_clock) -> str:
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.flush()
    post = Post(user_id=bob.id, brief="bob's", corpus_post_ids=[], created_at=fixed_clock())
    db.add(post)
    await db.commit()
    return post.id


async def test_another_users_post_is_not_found(client, subscribed, bobs_post_id):
    response = await client.get(f"{POSTS}/{bobs_post_id}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Post not found."


async def test_the_get_post_tool_reads_the_text_the_status_and_the_scheduled_post(
    client, post, mcp, fake_x_publisher
):
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Nope")
    failed = await _schedule(client, post["id"], publish_now=True)

    result = await mcp.call_tool("get_post", post_id=post["id"])

    assert result["isError"] is False
    read = result["structuredContent"]
    one = {"text": "Version one.", "char_count": 12, "char_limit": X_POST_MAX_CHARS}
    assert read == {
        "id": post["id"],
        "brief": "ship small things",
        "text": {"format": "post", "parts": [one], "version_number": 1, "edited": False},
        "versions": [
            {
                "id": post["versions"][0]["id"],
                "number": 1,
                "feedback": None,
                "format": "post",
                "parts": [one],
                "starting_text": None,
                "created_at": "2026-10-10T12:00:30Z",
            }
        ],
        "status": "failed",
        "scheduled_post": failed,
    }


async def test_the_get_post_tool_reads_a_draft_with_no_scheduled_post(post, mcp):
    read = (await mcp.call_tool("get_post", post_id=post["id"]))["structuredContent"]

    assert (read["status"], read["scheduled_post"]) == ("draft", None)


async def test_the_get_post_tool_says_another_users_post_is_not_found(
    subscribed, mcp, bobs_post_id
):
    result = await mcp.call_tool("get_post", post_id=bobs_post_id)

    assert error_text(result) == "Post not found."
