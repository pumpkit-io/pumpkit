"""The Post MCP tools, writing with the faked LLM and refusing what the web routes refuse."""

from datetime import datetime, timezone

import pytest

from pumpkit.authors.x_reader import FetchedPost


@pytest.fixture
async def with_author(subscribed, mcp, fake_x_reader):
    """`levelsio` on the User's list, with one stored post."""
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    assert (await mcp.call_tool("add_inspiration_author", handle="levelsio"))["isError"] is False


async def test_starting_a_post_returns_its_first_versions_final_and_character_count(
    with_author, mcp, fake_llm
):
    fake_llm.replies = [{"post": "the draft"}, {"post": "the final"}]

    result = await mcp.call_tool("start_post", brief="  ship small things ")

    assert result["isError"] is False
    post = result["structuredContent"]
    assert post["id"].startswith("post_")
    assert post == {
        "id": post["id"],
        "brief": "ship small things",
        "versions": [
            {
                "id": post["versions"][0]["id"],
                "number": 1,
                "feedback": None,
                "final": "the final",
                "final_char_count": 9,
            }
        ],
    }
