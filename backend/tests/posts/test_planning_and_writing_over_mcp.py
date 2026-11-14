"""
An AI app plans a Brief with `plan_posts`, which starts nothing, then writes the Ideas the User
picks with `write_posts` (ADR 0025).
"""

import pytest

from pumpkit.core.config import settings
from pumpkit.core.db.session import get_session_maker
from pumpkit.core.llm import LLMError
from pumpkit.main import app
from tests.mcp_client import error_text
from tests.positioning.positioning import save_positioning
from tests.posts.generations import use_a_generation
from tests.posts.writing_replies import (
    HUMANIZED_POST,
    PLAN,
    POST_IDEAS,
    ideas,
    planned_post,
)

POSTS = "/api/v1/posts"
USAGE = "/api/v1/usage"
BRIEF = "Three things I learned from my failed SaaS: pain, pricing and integrations."
CORE_IDEAS = [
    "Make sure the pain is real before you build.",
    "Charge at least 20 euros a month.",
    "Don't make OAuth integrations your core value.",
]
WHOLE = "Three lessons from a failed SaaS."


@pytest.fixture
async def ready(client, subscribed, writing_session_maker):
    await save_positioning(client)
    # Writes in parallel record their Versions at once, which SQLite takes only as write transactions.
    app.dependency_overrides[get_session_maker] = lambda: writing_session_maker


def _humanizer_naming_the_core_idea(call):
    text = "\n".join(str(message["content"]) for message in call.messages)
    for core_idea in [*CORE_IDEAS, WHOLE]:
        if core_idea in text:
            return {"post": f"Post on: {core_idea}", "first_reply": None}
    raise AssertionError("The humanizer was sent no known core idea")


@pytest.fixture
def split(fake_llm):
    """The planner finds three Ideas in the Brief; each Post's text names its core idea."""
    fake_llm.standing[POST_IDEAS] = {
        **ideas(planned_post(WHOLE), [planned_post(core_idea) for core_idea in CORE_IDEAS]),
        "reasoning": "Three separate lessons.",
    }
    fake_llm.standing[HUMANIZED_POST] = _humanizer_naming_the_core_idea


async def _plan(mcp, brief: str = BRIEF) -> dict:
    result = await mcp.call_tool("plan_posts", brief=brief)
    assert result["isError"] is False, result
    return result["structuredContent"]


async def _generations_used(client) -> int:
    return (await client.get(USAGE)).json()["allowance"]["generations"]["used"]


def _plan_of(core_idea: str) -> dict:
    return {**PLAN, "core_idea": core_idea}


async def test_plan_posts_answers_with_a_split_briefs_ideas_and_the_single_post_and_writes_nothing(
    client, ready, mcp, fake_llm, split, monkeypatch
):
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 2)

    planned = await _plan(mcp)

    assert planned["brief_id"].startswith("brief_")
    assert planned["ideas"] == [
        {
            "id": planned["ideas"][n]["id"],
            "posting_order": n + 1,
            "whole_brief": False,
            "plan": _plan_of(core_idea),
        }
        for n, core_idea in enumerate(CORE_IDEAS)
    ]
    assert planned["single_post"] == {
        "id": planned["single_post"]["id"],
        "posting_order": 1,
        "whole_brief": True,
        "plan": _plan_of(WHOLE),
    }
    assert planned["generations_left"] == 2
    assert len(fake_llm.calls) == 1
    assert await _generations_used(client) == 0
    assert (await client.get(POSTS)).json()["data"] == []


async def test_plan_posts_starts_no_post_for_a_brief_with_one_idea(client, ready, mcp, fake_llm):
    planned = await _plan(mcp, "One idea only.")

    assert planned["ideas"] == []
    assert planned["single_post"]["plan"] == PLAN
    assert len(fake_llm.calls) == 1
    assert (await client.get(POSTS)).json()["data"] == []
    assert await _generations_used(client) == 0


async def _write(mcp, planned: dict, idea_ids: list[str]) -> dict:
    return await mcp.call_tool("write_posts", brief_id=planned["brief_id"], idea_ids=idea_ids)


async def _text_of(mcp, post_id: str) -> list[str]:
    post = (await mcp.call_tool("get_post", post_id=post_id))["structuredContent"]
    assert post["writing_state"] is None
    return [part["text"] for part in post["text"]["parts"]]


async def test_write_posts_writes_the_picked_ideas_and_answers_with_their_post_ids(
    client, ready, mcp, fake_llm, split
):
    planned = await _plan(mcp)
    first, _, third = planned["ideas"]

    result = await _write(mcp, planned, [third["id"], first["id"]])

    assert result["isError"] is False, result
    written = result["structuredContent"]
    assert written["brief_id"] == planned["brief_id"]
    assert [(post["idea_id"], post["writing_state"]) for post in written["posts"]] == [
        (first["id"], "writing"),
        (third["id"], "writing"),
    ]
    first_post, third_post = (post["id"] for post in written["posts"])
    assert await _text_of(mcp, first_post) == [f"Post on: {CORE_IDEAS[0]}"]
    assert await _text_of(mcp, third_post) == [f"Post on: {CORE_IDEAS[2]}"]
    assert await _generations_used(client) == 2


async def test_write_posts_writes_the_single_post_covering_the_whole_brief(
    client, ready, mcp, fake_llm, split
):
    planned = await _plan(mcp)

    result = await _write(mcp, planned, [planned["single_post"]["id"]])

    [post] = result["structuredContent"]["posts"]
    assert post["idea_id"] == planned["single_post"]["id"]
    assert await _text_of(mcp, post["id"]) == [f"Post on: {WHOLE}"]
    assert await _generations_used(client) == 1


# What `plan_posts` and `write_posts` refuse, as tool errors with the web routes' words


async def test_plan_posts_is_refused_without_a_positioning_and_links_to_the_persona_page(
    subscribed, mcp, fake_llm
):
    result = await mcp.call_tool("plan_posts", brief=BRIEF)

    assert error_text(result) == (
        "Set up your persona before writing a post. http://localhost:5173/persona"
    )
    assert fake_llm.calls == []


async def test_plan_posts_shares_the_hourly_cap_on_plan_calls_with_the_web_app(
    client, ready, mcp, fake_llm, split, monkeypatch, fixed_clock
):
    monkeypatch.setattr("pumpkit.posts.plan_calls.PLAN_CALLS_PER_HOUR", 1)
    assert (await client.post("/api/v1/briefs", json={"brief": BRIEF})).status_code == 201
    fake_llm.calls.clear()

    result = await mcp.call_tool("plan_posts", brief=BRIEF)

    assert error_text(result) == "You've planned 1 briefs in the last hour."
    assert "retry_at" in result["structuredContent"]
    assert fake_llm.calls == []


async def test_a_failed_plan_call_is_a_reported_tool_error(ready, mcp, fake_llm, fake_posthog):
    fake_llm.standing[POST_IDEAS] = LLMError("provider down")

    result = await mcp.call_tool("plan_posts", brief=BRIEF)

    assert error_text(result) == "Writing the post failed. Please try again."
    error_id = result["structuredContent"]["error_id"]
    assert fake_posthog.capture_exception.call_args.kwargs["properties"]["error_id"] == error_id


async def test_write_posts_refuses_the_single_post_with_split_ideas(ready, mcp, fake_llm, split):
    planned = await _plan(mcp)

    result = await _write(mcp, planned, [planned["single_post"]["id"], planned["ideas"][0]["id"]])

    assert error_text(result) == (
        "Write one post covering everything, or one post per idea, not both."
    )
    assert len(fake_llm.calls) == 1


async def test_write_posts_refuses_an_idea_already_written(ready, mcp, fake_llm, split):
    planned = await _plan(mcp)
    first, second, _ = planned["ideas"]
    await _write(mcp, planned, [first["id"]])

    result = await _write(mcp, planned, [second["id"], first["id"]])

    assert error_text(result) == "One of these ideas is already written."
    assert result["structuredContent"] == {"code": "IDEAS_ALREADY_WRITTEN"}


async def test_write_posts_refuses_them_all_without_generations_left_for_all(
    client, db, user, ready, mcp, fake_llm, split, monkeypatch, fixed_clock
):
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 2)
    await use_a_generation(db, user.id)
    planned = await _plan(mcp)
    assert planned["generations_left"] == 1
    fake_llm.calls.clear()

    result = await _write(mcp, planned, [idea["id"] for idea in planned["ideas"][:2]])

    assert error_text(result) == (
        "Writing 2 posts needs 2 generations and you have 1 left. Write fewer. "
        "Failed attempts don't count. http://localhost:5173/settings"
    )
    assert (result["structuredContent"]["needed"], result["structuredContent"]["left"]) == (2, 1)
    assert fake_llm.calls == []
    brief = (await client.get(f"/api/v1/briefs/{planned['brief_id']}")).json()
    assert all(idea["post"] is None for idea in brief["ideas"])


async def test_write_posts_refuses_an_idea_of_another_brief(ready, mcp, fake_llm, split):
    planned = await _plan(mcp)
    other = await _plan(mcp)

    result = await _write(mcp, planned, [other["ideas"][0]["id"]])

    assert error_text(result) == "Idea not found."


async def test_write_posts_refuses_an_empty_pick(ready, mcp, fake_llm, split):
    planned = await _plan(mcp)

    result = await _write(mcp, planned, [])

    assert error_text(result) == "Pick at least one idea to write."


# The tools themselves


async def test_start_post_is_gone_and_the_two_steps_take_its_place(subscribed, mcp):
    tools = await mcp.list_tools()

    assert "start_post" not in tools
    assert list(tools["plan_posts"]["inputSchema"]["properties"]) == ["brief"]
    assert tools["write_posts"]["inputSchema"]["required"] == ["brief_id", "idea_ids"]
    for name in ("plan_posts", "write_posts"):
        # Planning stores a Brief and counts toward the hourly cap, so neither is read-only.
        assert tools[name]["annotations"] == {"readOnlyHint": False, "destructiveHint": False}


async def test_calling_start_post_is_an_unknown_tool_error(subscribed, mcp, fake_llm):
    result = await mcp.call_tool("start_post", brief=BRIEF)

    assert error_text(result) == "Unknown tool: start_post"
    assert fake_llm.calls == []


async def test_the_instructions_describe_positioning_and_the_two_steps(subscribed, mcp):
    instructions = (await mcp.initialize())["instructions"]

    assert "The user's positioning is a few sentences" in instructions
    assert "`set_positioning` saves it" in instructions
    assert "Writing posts takes two steps." in instructions
    assert "Show the user the core idea of each idea and ask which to write" in instructions
    assert "Call it only with the user's choice." in instructions
    assert "read each with `get_post` until `writing_state` is null" in instructions
    assert "start_post" not in instructions
