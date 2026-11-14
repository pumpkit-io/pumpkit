"""Inspiration authors are inactive (ADR 0024): the application mounts none of their routes or tools."""

from datetime import datetime, timezone

import pytest

from pumpkit.authors.x_reader import FetchedPost
from tests.mcp_client import error_text

AUTHOR_TOOLS = {"list_inspiration_authors", "add_inspiration_author", "remove_inspiration_author"}


@pytest.fixture(autouse=True)
def levelsio_on_x(fake_x_reader):
    """A handle the routes and tools would accept, so only a missing mount refuses it."""
    posted_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    fake_x_reader.posts["levelsio"] = [FetchedPost(post_id="1", text="post", posted_at=posted_at)]


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/author-directory", None),
        ("GET", "/inspiration-authors", None),
        ("POST", "/inspiration-authors", {"handle": "levelsio"}),
        ("POST", "/inspiration-authors/levelsio/refresh", None),
        ("DELETE", "/inspiration-authors/levelsio", None),
    ],
)
async def test_the_author_routes_are_unavailable_in_the_assembled_app(
    client, subscribed, fake_x_reader, method, path, payload
):
    response = await client.request(method, f"/api/v1{path}", json=payload)

    assert response.status_code == 404
    assert fake_x_reader.calls == []


async def test_the_server_lists_none_of_the_author_tools(subscribed, mcp):
    tools = await mcp.list_tools()

    assert AUTHOR_TOOLS.isdisjoint(tools)
    assert "get_positioning" in tools


async def test_calling_an_author_tool_is_an_unknown_tool(subscribed, mcp, fake_x_reader):
    result = await mcp.call_tool("add_inspiration_author", handle="levelsio")

    assert error_text(result) == "Unknown tool: add_inspiration_author"
    assert fake_x_reader.calls == []
