"""Starting a Post plans its Brief first, from the User's Positioning, and stores the Plan (ADR 0025)."""

import logging

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from pumpkit.core.config import settings
from pumpkit.core.llm import FakeLLM, LLMError, get_llm
from pumpkit.main import app
from pumpkit.posts.models import Brief, Idea, Post, VersionAttempt
from pumpkit.posts.writing import planning
from pumpkit.x_connection.x_publisher import XAccount
from tests.mcp_client import error_text
from tests.positioning.positioning import POSITIONING, TEXT, save_positioning
from tests.posts.writing_replies import (
    PLAN,
    POST_IDEAS,
    ideas,
    planned_post,
    planned_thread,
    written_post,
)

POSTS = "/api/v1/posts"
BRIEF = "I shipped a pricing page in a weekend and trials went from 12 to 31 a week."


@pytest.fixture
async def ready(client, subscribed):
    """A User who can start a Post: a Positioning saved, and no Inspiration authors."""
    await save_positioning(client)


@pytest.fixture
def premium(fake_x_publisher, connect_x):
    """Connects the User's X account as a Premium one, whose posts hold 25,000 characters."""

    async def _connect() -> None:
        fake_x_publisher.account = XAccount(
            user_id="1001", handle="ada", subscription_type="Premium"
        )
        await connect_x()

    return _connect


async def _start(client, fake_llm, brief: str = BRIEF):
    fake_llm.replies = [{"post": "the final"}]
    return await client.post(POSTS, json={"brief": brief})


def _system_text(call) -> str:
    return call.messages[0]["content"][0]["text"]


def _planned_schema(call) -> dict:
    """The schema of one planned single post in the answer the plan call asked for."""
    schema = call.response_model.model_json_schema()
    post, _thread = schema["properties"]["single_idea"]["anyOf"]
    return schema["$defs"][post["$ref"].rsplit("/", 1)[-1]]


async def _ideas(db) -> list[Idea]:
    """Every stored Idea: the single-post one first, then the split ones in posting order."""
    rows = await db.scalars(select(Idea).order_by(Idea.whole_brief.desc(), Idea.posting_order))
    return list(rows)


async def _count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_the_plan_call_comes_first_with_the_plan_prompt_the_brief_and_the_positioning(
    client, ready, fake_llm
):
    response = await _start(client, fake_llm, brief=f"  {BRIEF}\n")

    assert response.status_code == 201
    plan_call = fake_llm.calls[0]
    assert plan_call.response_model.__name__ == "post_ideas"
    assert plan_call.model == "openai/gpt-6-luna"
    system, user_message = plan_call.messages
    [block] = system["content"]
    assert (system["role"], block["type"]) == ("system", "text")
    assert block["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert block["text"].startswith("# Role\n\nYou plan posts on X on my behalf.")
    assert user_message == {
        "role": "user",
        "content": (f"<raw_input>\n{BRIEF}\n</raw_input>\n\n<positioning>\n{TEXT}\n</positioning>"),
    }
    assert len(fake_llm.calls) == 8


async def test_the_planning_model_is_its_own_setting(client, ready, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "LLM_PLANNING_MODEL", "acme/planner")

    await _start(client, fake_llm)

    plan_call, sketch_call, *_ = fake_llm.calls
    assert plan_call.model == "acme/planner"
    assert sketch_call.model == settings.LLM_SKETCHING_MODEL


async def test_the_answer_schema_puts_the_reasoning_before_the_plans_and_the_idea_before_the_choices(
    client, ready, fake_llm, premium
):
    await premium()

    await _start(client, fake_llm)

    schema = fake_llm.calls[0].response_model.model_json_schema()
    assert list(schema["properties"]) == ["reasoning", "single_idea", "split_ideas"]
    planned = _planned_schema(fake_llm.calls[0])
    assert list(planned["properties"]) == [
        "core_idea",
        "takeaway",
        "reasoning",
        "funnel",
        "desired_action",
        "format",
        "structure",
    ]
    assert planned["properties"]["format"]["enum"] == ["short", "medium", "long"]
    assert len(planned["properties"]["structure"]["enum"]) == 6


async def test_the_prompt_of_a_long_post_account_names_its_limit_and_offers_every_length(
    client, ready, fake_llm, premium
):
    await premium()

    await _start(client, fake_llm)

    prompt = _system_text(fake_llm.calls[0])
    assert "A post on my X account holds at most 25,000 characters." in prompt
    assert "- short: at most 280 characters" in prompt
    assert "- medium: about 350 to 600 characters (hard limit 700)." in prompt
    assert "- long: about 400 to 2,000 characters" in prompt
    assert "- hook_playbook_closer:" in prompt
    assert "- bookmark goes with a list, a playbook or a finding" in prompt
    assert "- format: short, medium, long or thread." in prompt
    assert "At least 2 ideas, at most 5." in prompt
    assert "{" not in prompt


async def test_the_prompt_of_a_280_character_account_offers_only_a_short_post_or_a_thread(
    client, ready, fake_llm
):
    await _start(client, fake_llm)

    prompt = _system_text(fake_llm.calls[0])
    assert "A post on my X account holds at most 280 characters." in prompt
    assert "- short: at most 280 characters" in prompt
    assert "- one_line:" in prompt and "- few_lines:" in prompt
    for longer in ("- medium:", "- long:"):
        assert longer not in prompt
    assert "one_line and few_lines are for a short post. A thread takes one of the other four." in (
        prompt
    )
    assert (
        "- A short post is one_line or few_lines. A thread is a list, a playbook, a problem or a "
        "story." in prompt
    )
    assert "- format: short or thread.\n" in prompt
    assert "{" not in prompt


async def test_a_280_character_account_takes_no_single_post_longer_than_short(
    client, ready, fake_llm, db, assert_reported_502
):
    fake_llm.standing[POST_IDEAS] = ideas(
        planned_post(format="medium", structure="hook_list_closer")
    )

    assert_reported_502(await _start(client, fake_llm))

    planned = _planned_schema(fake_llm.calls[0])
    assert planned["properties"]["format"] == {
        "const": "short",
        "title": "Format",
        "type": "string",
    }
    assert planned["properties"]["structure"]["enum"] == ["one_line", "few_lines"]
    assert await _count(db, Brief) == 0


async def test_the_post_is_returned_and_read_back_with_its_plan(client, ready, fake_llm, premium):
    await premium()
    fake_llm.standing[POST_IDEAS] = ideas(
        planned_post(
            "A weekend pricing page took trials from 12 to 31 a week.",
            funnel="MOF",
            desired_action="bookmark",
            format="medium",
            structure="hook_problem_insight_closer",
        )
    )

    started = (await _start(client, fake_llm)).json()

    plan = {
        "core_idea": "A weekend pricing page took trials from 12 to 31 a week.",
        "takeaway": "Ship the smallest thing that works this week.",
        "funnel": "middle",
        "desired_action": "bookmark",
        "format": "post",
        "length": "medium",
        "structure": "hook_problem_insight_closer",
    }
    assert started["plan"] == plan
    assert (await client.get(f"{POSTS}/{started['id']}")).json()["plan"] == plan


async def test_the_plan_of_a_thread_the_planner_chose_has_the_thread_format_and_no_length(
    client, ready, fake_llm
):
    fake_llm.standing[POST_IDEAS] = ideas(planned_thread(structure="hook_playbook_closer"))
    fake_llm.replies = [{"parts": ["final one", "final two"]}]

    response = await client.post(POSTS, json={"brief": BRIEF})

    started = await written_post(client, response)
    assert started["versions"][0]["format"] == "thread"
    assert started["plan"] == {
        **PLAN,
        "core_idea": "Five lessons from shipping small things every week.",
        "format": "thread",
        "length": None,
        "structure": "hook_playbook_closer",
    }
    read = (await client.get(f"{POSTS}/{started['id']}")).json()["plan"]
    assert (read["format"], read["length"]) == ("thread", None)


async def test_a_split_idea_can_be_a_thread_beside_a_single_post(client, ready, fake_llm, db):
    fake_llm.standing[POST_IDEAS] = ideas(
        split=[planned_thread("A playbook in steps."), planned_post("One sharp line.")]
    )

    await _start(client, fake_llm)

    _, thread, post = await _ideas(db)
    assert thread.plan is not None and post.plan is not None
    assert (thread.plan.format, thread.plan.length) == ("thread", None)
    assert (post.plan.format, post.plan.length) == ("post", "short")


@pytest.mark.parametrize(
    ("funnel", "stored"), [("TOF", "top"), ("MOF", "middle"), ("BOF", "bottom")]
)
async def test_the_funnel_is_stored_in_plain_words(client, ready, fake_llm, funnel, stored):
    fake_llm.standing[POST_IDEAS] = ideas(
        planned_post(funnel=funnel, desired_action="click", format="short", structure="one_line")
    )

    started = (await _start(client, fake_llm)).json()

    assert started["plan"]["funnel"] == stored


async def test_the_brief_stores_the_positioning_it_was_planned_with_and_the_planners_reasoning(
    client, ready, fake_llm, db, user
):
    reply = ideas()
    reply["reasoning"] = "One result with its numbers: one idea, no split."
    fake_llm.standing[POST_IDEAS] = reply

    await _start(client, fake_llm)
    changed = await client.put(POSITIONING, json={"text": "I post about gardening now."})
    assert changed.status_code == 200

    [brief] = list(await db.scalars(select(Brief)))
    assert (brief.user_id, brief.text, brief.positioning) == (user.id, BRIEF, TEXT)
    assert brief.planning_reasoning == "One result with its numbers: one idea, no split."
    assert brief.planning_model == "openai/gpt-6-luna"
    assert brief.planning_usage == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }


async def test_the_post_is_written_from_the_single_post_idea_and_split_plans_are_only_stored(
    client, ready, fake_llm, db, premium
):
    await premium()
    fake_llm.standing[POST_IDEAS] = ideas(
        planned_post(
            "Everything I learned from two failed products.",
            format="long",
            structure="hook_list_closer",
        ),
        split=[
            planned_post("Check the pain is real before building.", funnel="TOF"),
            planned_post("Charge from day one.", desired_action="trust"),
        ],
    )

    started = (await _start(client, fake_llm)).json()

    single, first, second = await _ideas(db)
    assert (single.whole_brief, single.posting_order) == (True, 1)
    assert single.plan is not None and single.plan.length == "long"
    assert [(idea.whole_brief, idea.posting_order) for idea in (first, second)] == [
        (False, 1),
        (False, 2),
    ]
    assert first.plan is not None and second.plan is not None
    assert (first.plan.core_idea, first.plan.funnel) == (
        "Check the pain is real before building.",
        "top",
    )
    assert (second.plan.core_idea, second.plan.desired_action) == ("Charge from day one.", "trust")
    assert second.plan.reasoning == (
        "The brief holds one result with its numbers, which earns trust."
    )
    [brief] = list(await db.scalars(select(Brief).options(selectinload(Brief.ideas))))
    assert [idea.id for idea in brief.ideas] == [single.id, first.id, second.id]
    [post] = list(await db.scalars(select(Post)))
    assert (post.id, post.idea_id) == (started["id"], single.id)
    assert started["plan"]["core_idea"] == "Everything I learned from two failed products."
    # One plan call and one Post's writing: five sketches, the merge, the humanizer.
    assert len(fake_llm.calls) == 8


async def test_at_most_five_split_plans_are_kept_in_the_planners_order(client, ready, fake_llm, db):
    fake_llm.standing[POST_IDEAS] = ideas(split=[planned_post(f"Idea {n}") for n in range(1, 8)])

    await _start(client, fake_llm)

    _, *kept = await _ideas(db)
    assert [(idea.posting_order, idea.core_idea) for idea in kept] == [
        (n, f"Idea {n}") for n in range(1, 6)
    ]


async def test_a_lone_split_plan_is_no_split(client, ready, fake_llm, db):
    fake_llm.standing[POST_IDEAS] = ideas(split=[planned_post("The only one")])

    await _start(client, fake_llm)

    assert [idea.whole_brief for idea in await _ideas(db)] == [True]


async def test_choices_that_pull_against_each_other_are_logged_and_the_post_is_still_written(
    client, ready, fake_llm, premium, caplog, user
):
    await premium()
    fake_llm.standing[POST_IDEAS] = ideas(
        planned_post(funnel="TOF", desired_action="buy", format="long", structure="few_lines")
    )

    with caplog.at_level(logging.WARNING, logger="pumpkit.posts.writing.planning"):
        response = await _start(client, fake_llm)

    logged = [record.getMessage() for record in caplog.records]
    assert logged == [
        f"A plan's choices pull against each other for User {user.id}: structure=few_lines is "
        "a short post: format=long is ignored and the post is planned short.",
        f"A plan's choices pull against each other for User {user.id}: desired_action=buy is "
        "unusual for the top of the funnel (usual: dwell_time, follow, reply, repost, share).",
    ]
    assert response.json()["plan"]["length"] == "short"
    assert (await written_post(client, response))["versions"][0]["parts"][0]["text"] == "the final"


async def test_a_list_planned_short_is_logged_as_tight(
    client, ready, fake_llm, premium, caplog, user
):
    await premium()
    fake_llm.standing[POST_IDEAS] = ideas(
        planned_post(format="short", structure="hook_list_closer")
    )

    with caplog.at_level(logging.WARNING, logger="pumpkit.posts.writing.planning"):
        response = await _start(client, fake_llm)

    assert response.status_code == 201
    assert [record.getMessage() for record in caplog.records] == [
        f"A plan's choices pull against each other for User {user.id}: "
        "structure=hook_list_closer in 280 characters is tight: expect a very compressed list."
    ]


async def test_starting_a_post_with_no_positioning_is_refused_with_the_persona_page_as_the_fix(
    client, subscribed, fake_llm, db
):
    response = await client.post(POSTS, json={"brief": BRIEF})

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Set up your persona before writing a post.",
        "url": "http://localhost:5173/persona",
    }
    assert fake_llm.calls == []
    assert await _count(db, Brief) == 0


async def test_start_post_over_mcp_is_refused_with_no_positioning_and_links_to_the_persona_page(
    subscribed, mcp, fake_llm
):
    result = await mcp.call_tool("start_post", brief=BRIEF)

    assert error_text(result) == (
        "Set up your persona before writing a post. http://localhost:5173/persona"
    )
    assert fake_llm.calls == []


async def test_a_failed_plan_call_stores_nothing_and_charges_nothing(
    client, ready, fake_llm, db, assert_reported_502
):
    fake_llm.standing[POST_IDEAS] = LLMError("gpt-6-luna: APIConnectionError: down")
    fake_llm.replies = [{"post": "the final"}]

    response = await client.post(POSTS, json={"brief": BRIEF})

    assert_reported_502(response)
    assert len(fake_llm.calls) == 1
    for model in (Brief, Idea, Post, VersionAttempt):
        assert await _count(db, model) == 0
    usage = (await client.get("/api/v1/usage")).json()
    assert usage["allowance"]["generations"]["used"] == 0


async def test_a_plan_call_that_runs_out_of_time_fails_like_any_other(
    client, ready, db, monkeypatch, assert_reported_502
):
    app.dependency_overrides[get_llm] = lambda: FakeLLM(latency=60)
    monkeypatch.setattr(planning, "PLAN_CALL_SECONDS", 0.01)

    response = await client.post(POSTS, json={"brief": BRIEF})

    assert_reported_502(response)
    assert await _count(db, Brief) == 0


async def test_a_post_whose_writing_failed_keeps_its_brief_and_plan(client, ready, fake_llm, db):
    fake_llm.replies = [LLMError("no reply")]

    assert (await client.post(POSTS, json={"brief": BRIEF})).status_code == 201

    [idea] = await _ideas(db)
    [post] = list(await db.scalars(select(Post)))
    assert post.idea_id == idea.id
    assert idea.plan is not None and idea.brief.positioning == TEXT


async def test_text_postgres_cannot_store_is_dropped_from_the_planners_answer(
    client, ready, fake_llm
):
    fake_llm.standing[POST_IDEAS] = ideas(
        planned_post("Ship\x00 small \ud83d things. ", format="short", structure="one_line")
    )

    started = (await _start(client, fake_llm)).json()

    assert started["plan"]["core_idea"] == "Ship small  things."
