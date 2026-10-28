"""The Post MCP tools, writing with the faked LLM and refusing what the web routes refuse."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from pumpkit.auth.models import User
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.posts.llm import LLMError
from pumpkit.posts.models import Post, VersionAttempt
from pumpkit.x_connection.x_length import X_POST_MAX_CHARS
from tests.mcp_client import error_text
from tests.posts.writing_replies import written, written_thread


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


async def test_the_writing_tools_only_add_and_the_reading_tools_only_read(subscribed, mcp):
    tools = await mcp.list_tools()

    for name in WRITING_TOOLS:
        assert tools[name]["annotations"] == {"readOnlyHint": False, "destructiveHint": False}
    for name in ("list_posts", "get_post"):
        assert tools[name]["annotations"]["readOnlyHint"] is True
    assert tools["give_feedback"]["inputSchema"]["required"] == ["post_id", "feedback"]
    assert tools["give_feedback"]["inputSchema"]["properties"]["format"]["default"] is None
    assert "draft" not in json.dumps(tools["get_post"]["outputSchema"])


async def test_starting_a_post_returns_its_first_versions_final_and_character_count(
    with_author, mcp, fake_llm
):
    fake_llm.replies = [written("the draft"), {"post": "the final"}]

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
                "format": "post",
                "parts": [{"text": "the final", "char_count": 9, "char_limit": X_POST_MAX_CHARS}],
            }
        ],
    }


async def test_starting_a_post_as_a_thread_returns_its_parts(with_author, mcp, fake_llm):
    fake_llm.replies = [
        written_thread(["draft one", "draft two"]),
        {"parts": ["final one", "final two 🚀"]},
    ]

    result = await mcp.call_tool("start_post", brief="ship small things", format="thread")

    assert result["isError"] is False
    [version] = result["structuredContent"]["versions"]
    assert (version["format"], version["parts"]) == (
        "thread",
        [
            {"text": "final one", "char_count": 9, "char_limit": 280},
            {"text": "final two 🚀", "char_count": 12, "char_limit": 280},
        ],
    )


async def test_start_post_takes_an_optional_format_of_post_or_thread(subscribed, mcp):
    schema = (await mcp.list_tools())["start_post"]["inputSchema"]

    assert schema["required"] == ["brief"]
    assert schema["properties"]["format"]["enum"] == ["post", "thread"]
    assert schema["properties"]["format"]["default"] == "post"


async def test_starting_a_post_without_authors_links_to_home(subscribed, mcp):
    result = await mcp.call_tool("start_post", brief="ship small things")

    assert error_text(result) == (
        "Add an Inspiration author with posts before writing a Post. http://localhost:5173/persona"
    )


@pytest.fixture
async def post_id(with_author, mcp, fake_llm) -> str:
    """A Post of the User's with one Version, whose Final is "final 1"."""
    fake_llm.replies = [written("draft 1"), {"post": "final 1"}]
    return (await mcp.call_tool("start_post", brief="ship small things"))["structuredContent"]["id"]


async def test_giving_feedback_returns_the_next_versions_final_and_character_count(
    post_id, mcp, fake_llm
):
    fake_llm.replies = [written("draft 2"), {"post": "shorter final"}]

    result = await mcp.call_tool("give_feedback", post_id=post_id, feedback=" shorter\n")

    assert result["isError"] is False
    version = result["structuredContent"]
    assert version == {
        "id": version["id"],
        "number": 2,
        "feedback": "shorter",
        "format": "post",
        "parts": [{"text": "shorter final", "char_count": 13, "char_limit": X_POST_MAX_CHARS}],
    }


async def test_feedback_with_a_format_switches_the_post_and_keeps_earlier_versions(
    post_id, mcp, fake_llm
):
    fake_llm.replies = [written_thread(["one", "two"]), {"parts": ["final one", "final two"]}]

    result = await mcp.call_tool(
        "give_feedback", post_id=post_id, feedback="expand it", format="thread"
    )

    assert result["isError"] is False
    assert result["structuredContent"]["format"] == "thread"
    versions = (await mcp.call_tool("get_post", post_id=post_id))["structuredContent"]["versions"]
    assert [(v["format"], [p["text"] for p in v["parts"]]) for v in versions] == [
        ("post", ["final 1"]),
        ("thread", ["final one", "final two"]),
    ]


async def test_feedback_without_a_format_keeps_the_latest_versions_thread(post_id, mcp, fake_llm):
    fake_llm.replies = [written_thread(["one", "two"]), {"parts": ["final one", "final two"]}]
    await mcp.call_tool("give_feedback", post_id=post_id, feedback="expand it", format="thread")
    fake_llm.replies = [written_thread(["one", "2"]), {"parts": ["final one", "final 2"]}]

    result = await mcp.call_tool("give_feedback", post_id=post_id, feedback="shorter Part 2")

    version = result["structuredContent"]
    assert (version["format"], [p["text"] for p in version["parts"]]) == (
        "thread",
        ["final one", "final 2"],
    )


async def test_feedback_through_the_tools_stores_the_revision_calls_hook_as_on_the_web_app(
    db, post_id, mcp, fake_llm
):
    reasoning = "The feedback asks to open with a rule, so my_rule fits."
    fake_llm.replies = [written("My rule.\n\ndraft 2", "my_rule", reasoning), {"post": "final 2"}]

    result = await mcp.call_tool("give_feedback", post_id=post_id, feedback="open with a rule")

    assert result["isError"] is False
    version = await db.scalar(
        select(VersionAttempt).where(VersionAttempt.id == result["structuredContent"]["id"])
    )
    assert version is not None
    assert (version.draft_parts, version.hook_name, version.hook_reasoning) == (
        ["My rule.\n\ndraft 2"],
        "my_rule",
        reasoning,
    )


async def test_reading_a_post_returns_every_version_but_not_failed_attempts(post_id, mcp, fake_llm):
    fake_llm.replies = [LLMError("provider down")]
    await mcp.call_tool("give_feedback", post_id=post_id, feedback="shorter")
    fake_llm.replies = [written("draft 2"), {"post": "final two"}]
    await mcp.call_tool("give_feedback", post_id=post_id, feedback="warmer")

    result = await mcp.call_tool("get_post", post_id=post_id)

    assert result["isError"] is False
    post = result["structuredContent"]
    assert post["id"] == post_id
    assert post["brief"] == "ship small things"
    assert [
        (version["number"], version["feedback"], version["format"], version["parts"])
        for version in post["versions"]
    ] == [
        (1, None, "post", [{"text": "final 1", "char_count": 7, "char_limit": X_POST_MAX_CHARS}]),
        (
            2,
            "warmer",
            "post",
            [{"text": "final two", "char_count": 9, "char_limit": X_POST_MAX_CHARS}],
        ),
    ]
    assert "draft_parts" not in post["versions"][0]


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
        fake_llm.replies = [written("draft"), {"post": "final"}]
        await mcp.call_tool("start_post", brief=brief)
        fixed_clock.advance(timedelta(minutes=1))
    fake_llm.replies = [written("draft"), {"post": "final"}]
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


def _writing_call(tool: str, post_id: str) -> dict[str, str]:
    """The arguments of a call to the writing `tool`, on `post_id` when it takes one."""
    if tool == "start_post":
        return {"brief": "ship"}
    return {"post_id": post_id, "feedback": "shorter"}


WRITING_TOOLS = ["start_post", "give_feedback"]


@pytest.mark.parametrize("tool", WRITING_TOOLS)
async def test_a_model_failure_is_a_reported_tool_error(post_id, mcp, fake_llm, fake_posthog, tool):
    fake_llm.replies = [LLMError("provider down")]

    result = await mcp.call_tool(tool, **_writing_call(tool, post_id))

    assert error_text(result) == "Writing the Post failed. Please try again."
    error_id = result["structuredContent"]["error_id"]
    assert fake_posthog.capture_exception.call_args.kwargs["properties"]["error_id"] == error_id


@pytest.mark.parametrize("tool", WRITING_TOOLS)
async def test_attempts_through_the_web_routes_count_toward_the_hourly_attempt_limit(
    post_id, client, db, user, mcp, fake_llm, fixed_clock, tool
):
    # With the fixture's first Version, 29 attempts; the web route makes the 30th.
    earlier = Post(user_id=user.id, brief="earlier", corpus_post_ids=[], created_at=fixed_clock())
    db.add(earlier)
    await db.flush()
    for sequence in range(1, 29):
        db.add(
            VersionAttempt(
                post_id=earlier.id,
                sequence=sequence,
                format="post",
                status="failed",
                error="LLMError: down",
                created_at=fixed_clock(),
            )
        )
    await db.commit()
    fixed_clock.advance(timedelta(minutes=10))
    fake_llm.replies = [written("draft"), {"post": "final"}]
    assert (await client.post("/api/v1/posts", json={"brief": "ship"})).status_code == 201
    fake_llm.calls.clear()

    result = await mcp.call_tool(tool, **_writing_call(tool, post_id))

    assert error_text(result) == "You've made 30 attempts at a Version in the last hour."
    assert result["structuredContent"] == {"retry_at": "2026-10-10T13:00:30Z"}
    assert fake_llm.calls == []


@pytest.mark.parametrize(
    ("tool", "arguments", "per_minute"),
    [
        ("start_post", {"brief": "ship"}, 20),
        ("give_feedback", {"post_id": "post_missing", "feedback": "shorter"}, 20),
        ("list_posts", {}, 60),
        ("get_post", {"post_id": "post_missing"}, 60),
    ],
)
async def test_each_tool_has_its_per_user_limit_a_minute(
    subscribed, client, mcp, tool, arguments, per_minute
):
    for _ in range(per_minute):
        await mcp.call_tool(tool, **arguments)

    result = await mcp.call_tool(tool, **arguments)

    assert error_text(result).startswith(f"You've called {tool} too often.")
    assert "retry_at" in result["structuredContent"]
    # Counted per User, so the web route from the same address still answers.
    assert (
        await client.post("/api/v1/posts/post_missing/versions", json={"feedback": "x"})
    ).status_code == 404
