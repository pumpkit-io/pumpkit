"""The Inspiration author MCP tools, refusing what the web routes refuse, in the same words."""

from datetime import datetime, timedelta, timezone

import pytest

from pumpkit.authors.x_reader import FetchedPost
from tests.mcp_client import error_text


def _posts(*ids: str) -> list[FetchedPost]:
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return [
        FetchedPost(post_id=post_id, text=f"post {post_id}", posted_at=start - timedelta(hours=i))
        for i, post_id in enumerate(ids)
    ]


@pytest.fixture(autouse=True)
def known_handles(fake_x_reader):
    for handle in ("levelsio", "paulg", "naval", "dhh"):
        fake_x_reader.posts[handle] = _posts(f"{handle}-1", f"{handle}-2")
        fake_x_reader.photos[handle] = f"https://pbs.twimg.com/profile_images/1/{handle}_normal.jpg"


async def test_adding_a_handle_lists_it_with_its_fetched_posts(
    subscribed, mcp, fake_x_reader, fixed_clock
):
    result = await mcp.call_tool("add_inspiration_author", handle="@LevelsIO")

    assert result["isError"] is False
    assert result["structuredContent"] == {
        "handle": "levelsio",
        "last_fetched_at": "2026-10-10T12:00:30Z",
        "post_count": 2,
    }
    assert fake_x_reader.calls == ["levelsio"]
    listed = await mcp.call_tool("list_inspiration_authors")
    assert listed["structuredContent"] == {"data": [result["structuredContent"]]}


async def test_the_list_shows_authors_in_the_order_they_were_added(subscribed, mcp):
    await mcp.call_tool("add_inspiration_author", handle="paulg")
    await mcp.call_tool("add_inspiration_author", handle="levelsio")

    result = await mcp.call_tool("list_inspiration_authors")

    handles = [author["handle"] for author in result["structuredContent"]["data"]]
    assert handles == ["paulg", "levelsio"]


async def test_adding_a_listed_handle_is_refused(subscribed, mcp):
    await mcp.call_tool("add_inspiration_author", handle="levelsio")

    result = await mcp.call_tool("add_inspiration_author", handle="@levelsio")

    assert error_text(result) == "@levelsio is already one of your inspiration authors."


async def test_a_fourth_author_is_refused(subscribed, mcp):
    for handle in ("levelsio", "paulg", "naval"):
        await mcp.call_tool("add_inspiration_author", handle=handle)

    result = await mcp.call_tool("add_inspiration_author", handle="dhh")

    assert error_text(result) == (
        "You can have up to 3 Inspiration authors. Remove one to add another."
    )


async def test_a_handle_that_isnt_valid_is_refused_without_reading_x(
    subscribed, mcp, fake_x_reader
):
    result = await mcp.call_tool("add_inspiration_author", handle="levels io")

    assert error_text(result) == "An X handle holds only letters, digits and underscores."
    assert fake_x_reader.calls == []


async def test_a_handle_x_doesnt_know_is_refused(subscribed, mcp):
    result = await mcp.call_tool("add_inspiration_author", handle="nobody")

    assert error_text(result) == "@nobody doesn't exist on X."


async def test_a_handle_without_original_posts_is_refused(subscribed, mcp, fake_x_reader):
    fake_x_reader.posts["quiet"] = []

    result = await mcp.call_tool("add_inspiration_author", handle="quiet")

    assert error_text(result) == "@quiet has no original posts to learn from."


async def test_x_unreadable_is_refused_and_reported(subscribed, mcp, fake_x_reader, fake_posthog):
    fake_x_reader.fail = True

    result = await mcp.call_tool("add_inspiration_author", handle="levelsio")

    assert error_text(result) == "X can't be read right now. Please try again later."
    error_id = result["structuredContent"]["error_id"]
    fake_posthog.capture_exception.assert_called_once()
    assert fake_posthog.capture_exception.call_args.kwargs["properties"]["error_id"] == error_id
    assert (await mcp.call_tool("list_inspiration_authors"))["structuredContent"] == {"data": []}


async def test_removing_an_author_takes_it_off_the_list(subscribed, mcp):
    await mcp.call_tool("add_inspiration_author", handle="levelsio")
    await mcp.call_tool("add_inspiration_author", handle="paulg")

    result = await mcp.call_tool("remove_inspiration_author", handle="@LevelsIO")

    assert result["structuredContent"] == {
        "message": "@levelsio is no longer one of your inspiration authors."
    }
    listed = await mcp.call_tool("list_inspiration_authors")
    assert [author["handle"] for author in listed["structuredContent"]["data"]] == ["paulg"]


@pytest.mark.parametrize("handle", ["levelsio", "not a handle"])
async def test_removing_a_handle_that_isnt_listed_is_refused(subscribed, mcp, handle):
    result = await mcp.call_tool("remove_inspiration_author", handle=handle)

    assert error_text(result) == "That handle isn't one of your inspiration authors."
