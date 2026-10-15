"""The Scheduled post MCP tools, refusing what the web routes refuse, in the same words."""

from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient

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
