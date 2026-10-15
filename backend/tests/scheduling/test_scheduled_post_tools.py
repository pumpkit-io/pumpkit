"""The Scheduled post MCP tools, refusing what the web routes refuse, in the same words."""

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient

from pumpkit.auth.models import User
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.posts.models import ATTEMPT_SUCCEEDED, Post, VersionAttempt
from tests.mcp_client import error_text

SCHEDULED_PAGE = "http://localhost:5173/scheduled"


async def _connect_x(client: AsyncClient) -> None:
    started = await client.post("/api/v1/x-connection/authorizations")
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
    completed = await client.post(
        "/api/v1/x-connection/authorizations/complete", json={"code": "c", "state": state}
    )
    assert completed.status_code == 200, completed.text


@pytest.fixture
async def connected(client, subscribed, fake_x_publisher) -> None:
    await _connect_x(client)


@pytest.fixture
async def version(client, subscribed, fake_x_reader, fake_llm) -> dict:
    """The first Version of a new Post, whose Final is "The final, version one."."""
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    added = await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    assert added.status_code == 201, added.text
    fake_llm.replies = [{"post": "draft one"}, {"post": "The final, version one."}]
    started = await client.post("/api/v1/posts", json={"brief": "ship small things"})
    assert started.status_code == 201, started.text
    return started.json()["versions"][0]


async def test_scheduling_typed_text_lists_it_with_the_scheduled_page_link(
    connected, mcp, fixed_clock
):
    result = await mcp.call_tool(
        "schedule_post", text="  Shipping on Monday.  ", publish_at="2026-10-10T16:00:00+02:00"
    )

    assert result["isError"] is False, result
    scheduled = result["structuredContent"]
    assert scheduled["text"] == "Shipping on Monday."
    assert scheduled["state"] == "scheduled"
    assert scheduled["publish_at"] == "2026-10-10T14:00:00Z"
    assert scheduled["source_version_id"] is None
    assert scheduled["community"] is None
    assert scheduled["scheduled_page_url"] == SCHEDULED_PAGE
    listed = await mcp.call_tool("list_scheduled_posts")
    assert listed["structuredContent"] == {
        "data": [{key: value for key, value in scheduled.items() if key != "scheduled_page_url"}],
        "scheduled_page_url": SCHEDULED_PAGE,
    }


async def test_scheduling_a_version_copies_its_final_and_records_the_version(
    connected, version, mcp, fixed_clock
):
    result = await mcp.call_tool(
        "schedule_post", version_id=version["id"], publish_at="2026-10-10T14:00:00Z"
    )

    assert result["isError"] is False, result
    assert result["structuredContent"]["text"] == "The final, version one."
    assert result["structuredContent"]["source_version_id"] == version["id"]


async def test_scheduling_another_users_version_is_refused_as_not_found(
    connected, mcp, db, fixed_clock
):
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.flush()
    bobs_post = Post(user_id=bob.id, brief="bob's", corpus_post_ids=[], created_at=fixed_clock())
    db.add(bobs_post)
    await db.flush()
    bobs_version = VersionAttempt(
        post_id=bobs_post.id,
        sequence=1,
        status=ATTEMPT_SUCCEEDED,
        version_number=1,
        final="Bob's words.",
        created_at=fixed_clock(),
    )
    db.add(bobs_version)
    await db.commit()

    result = await mcp.call_tool(
        "schedule_post", version_id=bobs_version.id, publish_at="2026-10-10T14:00:00Z"
    )

    assert error_text(result) == "Version not found."
    assert (await mcp.call_tool("list_scheduled_posts"))["structuredContent"]["data"] == []


@pytest.mark.parametrize("arguments", [{}, {"text": "Mine.", "version_id": "version_attempt_1"}])
async def test_scheduling_needs_either_text_or_a_version(connected, mcp, fixed_clock, arguments):
    result = await mcp.call_tool("schedule_post", publish_at="2026-10-10T14:00:00Z", **arguments)

    assert error_text(result) == "Give either the text or a Version id, not both."
