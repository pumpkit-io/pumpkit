"""
Restoring a Version as the Post's Text (ADR 0016), through
`POST /posts/{id}/versions/{number}/restore` and the `restore_version` tool. Only a Draft or a
Failed Post's Text changes.
"""

from datetime import datetime, timezone

import pytest

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.mcp_server import INSTRUCTIONS
from pumpkit.posts.models import Post
from pumpkit.x_connection.x_length import X_POST_MAX_CHARS
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.mcp_client import error_text
from tests.posts.writing_replies import written, written_thread

POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
LATER = "2026-10-10T14:00:00Z"
SCHEDULED_TEXT_IS_SET = (
    "This Post is scheduled, so its Text is set. Edit its Scheduled post, or unschedule it first."
)
PUBLISHED_TEXT_IS_SET = (
    "This Post is published, so its Text is set. Start a new Post to write another."
)
ONE = {"text": "Version one.", "char_count": 12, "char_limit": X_POST_MAX_CHARS}


@pytest.fixture
async def post(client, subscribed, fake_x_reader, fake_llm, fixed_clock, connect_x) -> dict:
    """A Post with two Versions, a single post then a Thread, so its Text is Version 2."""
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
    started = await client.post(POSTS, json={"brief": "ship small things"})
    assert started.status_code == 201, started.text
    fake_llm.replies = [written_thread(["one", "two"]), {"parts": ["Part one.", "Part two."]}]
    given = await client.post(
        f"{POSTS}/{started.json()['id']}/versions",
        json={"feedback": "expand it", "format": "thread"},
    )
    assert given.status_code == 201, given.text
    return (await client.get(f"{POSTS}/{started.json()['id']}")).json()


async def _restore(client, post_id: str, number: int):
    return await client.post(f"{POSTS}/{post_id}/versions/{number}/restore")


async def _schedule(client, post: dict, **when) -> dict:
    response = await client.post(SCHEDULED_POSTS, json={"post_id": post["id"], **when})
    assert response.status_code == 201, response.text
    return response.json()


async def test_restoring_a_version_makes_it_the_text(client, post):
    response = await _restore(client, post["id"], 1)

    assert response.status_code == 200, response.text
    restored = {"format": "post", "parts": [ONE], "version_number": 1, "edited": False}
    assert response.json() == restored
    read = (await client.get(f"{POSTS}/{post['id']}")).json()
    assert read["text"] == restored
    assert [v["number"] for v in read["versions"]] == [1, 2]


async def test_restoring_clears_the_edited_flag(client, db_session_maker, post):
    async with db_session_maker() as session:
        stored = await session.get(Post, post["id"])
        assert stored is not None
        stored.text_parts = ["Part one, by hand.", "Part two."]
        stored.text_edited = True
        await session.commit()

    response = await _restore(client, post["id"], 2)

    assert response.status_code == 200, response.text
    assert response.json()["edited"] is False
    assert [p["text"] for p in response.json()["parts"]] == ["Part one.", "Part two."]


async def test_restoring_on_a_failed_post_makes_it_the_text(client, fake_x_publisher, post):
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Nope")
    assert (await _schedule(client, post, publish_now=True))["state"] == "failed"

    response = await _restore(client, post["id"], 1)

    assert response.status_code == 200, response.text
    assert response.json()["version_number"] == 1


async def test_restoring_on_a_scheduled_post_is_refused_naming_the_fix(client, post):
    await _schedule(client, post, publish_at=LATER)

    response = await _restore(client, post["id"], 1)

    assert response.status_code == 409
    assert response.json()["detail"] == SCHEDULED_TEXT_IS_SET
    assert (await client.get(f"{POSTS}/{post['id']}")).json()["text"]["version_number"] == 2


async def test_restoring_on_a_published_post_is_refused_naming_the_fix(client, post):
    await _schedule(client, post, publish_now=True)

    response = await _restore(client, post["id"], 1)

    assert response.status_code == 409
    assert response.json()["detail"] == PUBLISHED_TEXT_IS_SET


async def test_restoring_a_version_the_post_does_not_have_is_not_found(client, post):
    response = await _restore(client, post["id"], 3)

    assert response.status_code == 404
    assert response.json()["detail"] == "This Post has no Version 3."


async def test_restoring_on_someone_else_s_post_is_not_found(client, subscribed):
    response = await _restore(client, "post_01M4JS3D7BER5QZANNA2D0EFRQ", 1)

    assert response.status_code == 404
    assert response.json()["detail"] == "Post not found."


async def test_restoring_needs_a_subscription(client, db, post, subscribed):
    await db.delete(subscribed)
    await db.commit()

    response = await _restore(client, post["id"], 1)

    assert response.status_code == 403


async def test_the_restore_version_tool_answers_with_the_text(client, post, mcp):
    result = await mcp.call_tool("restore_version", post_id=post["id"], version_number=1)

    assert result["isError"] is False, result
    assert result["structuredContent"] == {
        "format": "post",
        "parts": [ONE],
        "version_number": 1,
        "edited": False,
    }
    assert (await client.get(f"{POSTS}/{post['id']}")).json()["text"]["version_number"] == 1


async def test_the_restore_version_tool_refuses_a_scheduled_post(client, post, mcp):
    await _schedule(client, post, publish_at=LATER)

    result = await mcp.call_tool("restore_version", post_id=post["id"], version_number=1)

    assert error_text(result) == SCHEDULED_TEXT_IS_SET


async def test_the_restore_version_tool_says_a_missing_version_is_not_found(post, mcp):
    result = await mcp.call_tool("restore_version", post_id=post["id"], version_number=9)

    assert error_text(result) == "This Post has no Version 9."


def test_the_server_instructions_mention_restoring_a_version():
    assert "restore_version" in INSTRUCTIONS
