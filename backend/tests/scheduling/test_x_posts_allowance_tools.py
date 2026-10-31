"""`schedule_post`, `post_now` and `edit_scheduled_post` refuse at the X posts limit as the web does."""

import pytest

from pumpkit.core.config import settings
from tests.mcp_client import error_text

REFUSAL = (
    "You've used this period's 1 X posts. They reset on 1 November. http://localhost:5173/settings"
)


@pytest.fixture
async def one_x_post_used(subscribed, fixed_clock, connect_x, mcp, post_with, monkeypatch):
    """The `subscribed` User's period runs from 1 October, and its one X post is scheduled."""
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 1)
    await connect_x()
    result = await mcp.call_tool(
        "schedule_post", post_id=await post_with("One"), publish_at="2026-10-11T09:00:00Z"
    )
    assert result["isError"] is False, result
    return result["structuredContent"]


async def test_schedule_post_refuses_with_no_x_posts_left_and_links_to_settings(
    one_x_post_used, mcp, post_with
):
    result = await mcp.call_tool(
        "schedule_post", post_id=await post_with("Two"), publish_at="2026-10-12T09:00:00Z"
    )

    assert result["isError"] is True
    assert error_text(result) == REFUSAL
    assert result["structuredContent"] == {
        "url": "http://localhost:5173/settings",
        "code": "ALLOWANCE_USED_UP",
        "ran_out": "x_posts",
        "needed": 1,
        "left": 0,
        "resets_at": "2026-11-01T00:00:00Z",
        "way_out": None,
    }


async def test_post_now_refuses_with_no_x_posts_left(
    one_x_post_used, mcp, post_with, fake_x_publisher
):
    result = await mcp.call_tool("post_now", post_id=await post_with("Now"))

    assert result["isError"] is True
    assert error_text(result) == REFUSAL
    assert fake_x_publisher.published == []


async def test_edit_scheduled_post_refuses_parts_that_dont_fit(one_x_post_used, mcp):
    result = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=one_x_post_used["id"], parts=["One", "Two"]
    )

    assert result["isError"] is True
    assert error_text(result) == (
        "This thread needs 2 X posts and you have 1 left. Schedule it after 1 November. "
        "http://localhost:5173/settings"
    )
