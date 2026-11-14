"""`start_post` and `give_feedback` refuse at the Generations limit as the web routes do."""

import pytest

from pumpkit.core.config import settings
from tests.mcp_client import error_text
from tests.posts.generations import use_a_generation

REFUSAL = (
    "You've used this period's 2 generations. They reset on 1 November. "
    "Failed attempts don't count. http://localhost:5173/settings"
)


@pytest.fixture
async def with_positioning(subscribed, mcp, monkeypatch):
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 2)
    assert (await mcp.call_tool("set_positioning", text="I post about bootstrapping."))[
        "isError"
    ] is False


async def test_start_post_refuses_with_no_generations_left_and_links_to_settings(
    db, user, with_positioning, mcp, fake_llm, fixed_clock
):
    await use_a_generation(db, user.id)
    await use_a_generation(db, user.id)

    result = await mcp.call_tool("start_post", brief="ship")

    assert result["isError"] is True
    assert error_text(result) == REFUSAL
    assert result["structuredContent"] == {
        "url": "http://localhost:5173/settings",
        "code": "ALLOWANCE_USED_UP",
        "ran_out": "generations",
        "needed": 1,
        "left": 0,
        "resets_at": "2026-11-01T00:00:00Z",
        "way_out": None,
    }
    assert fake_llm.calls == []


async def test_give_feedback_refuses_with_no_generations_left(
    db, user, with_positioning, mcp, fake_llm, fixed_clock
):
    fake_llm.replies = [{"post": "final"}]
    post_id = (await mcp.call_tool("start_post", brief="ship"))["structuredContent"]["id"]
    await use_a_generation(db, user.id)
    fake_llm.calls.clear()

    result = await mcp.call_tool("give_feedback", post_id=post_id, feedback="shorter")

    assert result["isError"] is True
    assert error_text(result) == REFUSAL
    assert fake_llm.calls == []
