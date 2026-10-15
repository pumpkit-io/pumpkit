"""The Post MCP tools, writing with the faked LLM and refusing what the web routes refuse."""

from datetime import datetime, timedelta, timezone

import pytest

from pumpkit.auth.models import User
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.posts.llm import LLMError
from pumpkit.posts.models import Post
from tests.mcp_client import error_text


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


@pytest.fixture
async def post_id(with_author, mcp, fake_llm) -> str:
    """A Post of the User's with one Version, whose Final is "final 1"."""
    fake_llm.replies = [{"post": "draft 1"}, {"post": "final 1"}]
    return (await mcp.call_tool("start_post", brief="ship small things"))["structuredContent"]["id"]


async def test_giving_feedback_returns_the_next_versions_final_and_character_count(
    post_id, mcp, fake_llm
):
    fake_llm.replies = [{"post": "draft 2"}, {"post": "shorter final"}]

    result = await mcp.call_tool("give_feedback", post_id=post_id, feedback=" shorter\n")

    assert result["isError"] is False
    version = result["structuredContent"]
    assert version == {
        "id": version["id"],
        "number": 2,
        "feedback": "shorter",
        "final": "shorter final",
        "final_char_count": 13,
    }


async def test_reading_a_post_returns_every_version_but_not_failed_attempts(
    post_id, mcp, fake_llm
):
    fake_llm.replies = [LLMError("provider down")]
    await mcp.call_tool("give_feedback", post_id=post_id, feedback="shorter")
    fake_llm.replies = [{"post": "draft 2"}, {"post": "final two"}]
    await mcp.call_tool("give_feedback", post_id=post_id, feedback="warmer")

    result = await mcp.call_tool("get_post", post_id=post_id)

    assert result["isError"] is False
    post = result["structuredContent"]
    assert post["id"] == post_id
    assert post["brief"] == "ship small things"
    assert [
        (version["number"], version["feedback"], version["final"], version["final_char_count"])
        for version in post["versions"]
    ] == [(1, None, "final 1", 7), (2, "warmer", "final two", 9)]
    assert "draft" not in post["versions"][0]


@pytest.fixture
async def bobs_post_id(db, fixed_clock) -> str:
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.flush()
    post = Post(user_id=bob.id, brief="bob's", corpus_post_ids=[], created_at=fixed_clock())
    db.add(post)
    await db.commit()
    return post.id


@pytest.mark.parametrize(
    ("tool", "arguments"), [("get_post", {}), ("give_feedback", {"feedback": "shorter"})]
)
async def test_another_users_post_reads_as_not_found(
    subscribed, mcp, bobs_post_id, fake_llm, tool, arguments
):
    result = await mcp.call_tool(tool, post_id=bobs_post_id, **arguments)

    assert error_text(result) == "Post not found."
    assert fake_llm.calls == []


async def test_listing_posts_pages_through_the_users_posts_newest_first(
    with_author, mcp, fake_llm, fixed_clock, bobs_post_id
):
    for brief in ("first", "second", "third"):
        fake_llm.replies = [{"post": "draft"}, {"post": "final"}]
        await mcp.call_tool("start_post", brief=brief)
        fixed_clock.advance(timedelta(minutes=1))
    fake_llm.replies = [{"post": "draft"}, {"post": "final"}]
    third_id = (await mcp.call_tool("list_posts"))["structuredContent"]["data"][0]["id"]
    await mcp.call_tool("give_feedback", post_id=third_id, feedback="shorter")

    first_page = await mcp.call_tool("list_posts", limit=2)
    second_page = await mcp.call_tool("list_posts", limit=2, offset=2)

    assert first_page["isError"] is False
    assert first_page["structuredContent"] == {
        "data": [
            {
                "id": third_id,
                "brief": "third",
                "created_at": "2026-10-10T12:02:30Z",
                "version_count": 2,
            },
            {
                "id": first_page["structuredContent"]["data"][1]["id"],
                "brief": "second",
                "created_at": "2026-10-10T12:01:30Z",
                "version_count": 1,
            },
        ],
        "next_offset": 2,
    }
    assert [post["brief"] for post in second_page["structuredContent"]["data"]] == ["first"]
    assert second_page["structuredContent"]["next_offset"] is None


async def test_a_user_without_posts_lists_none(subscribed, mcp):
    result = await mcp.call_tool("list_posts")

    assert result["structuredContent"] == {"data": [], "next_offset": None}


@pytest.mark.parametrize(
    ("arguments", "detail"),
    [
        ({"limit": 0}, "Input should be greater than or equal to 1"),
        ({"limit": 51}, "Input should be less than or equal to 50"),
        ({"offset": -1}, "Input should be greater than or equal to 0"),
    ],
)
async def test_a_page_outside_the_bounds_is_refused(subscribed, mcp, arguments, detail):
    result = await mcp.call_tool("list_posts", **arguments)

    assert error_text(result) == detail
