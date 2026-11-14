"""
Planning a Brief is its own request, and a second one writes the Ideas the User picks, each as a
Post written in parallel in the background (ADR 0025, ADR 0026).
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pytest

from pumpkit.core.config import settings
from pumpkit.core.db.session import get_session_maker
from pumpkit.core.llm import FakeLLM, LLMCall, LLMError, StructuredResult, get_llm
from pumpkit.main import app
from pumpkit.posts.models import Post, VersionAttempt
from tests.mcp_client import error_text
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import (
    HUMANIZED_POST,
    MERGED_SKETCH,
    POST_IDEAS,
    SKETCHED_POST,
    ideas,
    merged,
    planned_post,
    sketched,
)

BRIEFS = "/api/v1/briefs"
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


def _text_of(call: LLMCall) -> str:
    return "\n".join(
        part["text"] if isinstance(part, dict) else str(part)
        for message in call.messages
        for part in (
            message["content"] if isinstance(message["content"], list) else [message["content"]]
        )
    )


def _humanizer_writing(fails: tuple[str, ...] = ()):
    """A humanizer reply naming the core idea it was asked to write, or a failure for `fails`."""

    def reply(call: LLMCall):
        text = _text_of(call)
        for core_idea in [*CORE_IDEAS, WHOLE]:
            if core_idea in text:
                if core_idea in fails:
                    return LLMError("provider down")
                return {"post": f"Post on: {core_idea}", "first_reply": None}
        raise AssertionError("The humanizer was sent no known core idea")

    return reply


@pytest.fixture
def split(fake_llm):
    """The planner finds three Ideas in the Brief; each Post's text names its core idea."""
    fake_llm.standing[POST_IDEAS] = {
        **ideas(planned_post(WHOLE), [planned_post(core_idea) for core_idea in CORE_IDEAS]),
        "reasoning": "Three separate lessons.",
    }
    fake_llm.standing[HUMANIZED_POST] = _humanizer_writing()


async def _plan(client, brief: str = BRIEF) -> dict:
    response = await client.post(BRIEFS, json={"brief": brief})
    assert response.status_code == 201, response.text
    return response.json()


def _split_ideas(brief: dict) -> list[dict]:
    return [idea for idea in brief["ideas"] if not idea["whole_brief"]]


def _whole_idea(brief: dict) -> dict:
    [idea] = [idea for idea in brief["ideas"] if idea["whole_brief"]]
    return idea


async def _write(client, brief: dict, idea_ids: list[str]):
    return await client.post(f"{BRIEFS}/{brief['id']}/posts", json={"idea_ids": idea_ids})


async def _read(client, brief_id: str) -> dict:
    response = await client.get(f"{BRIEFS}/{brief_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _posts_by_core_idea(brief: dict) -> dict[str, dict]:
    return {idea["plan"]["core_idea"]: idea["post"] for idea in brief["ideas"] if idea["post"]}


def _texts(brief: dict) -> dict[str, list[str]]:
    return {
        core_idea: [part["text"] for part in post["text"]["parts"]] if post["text"] else []
        for core_idea, post in _posts_by_core_idea(brief).items()
    }


async def _generations_used(client) -> int:
    return (await client.get(USAGE)).json()["allowance"]["generations"]["used"]


async def _until(condition: Callable[[], bool]) -> None:
    while not condition():
        await asyncio.sleep(0)


def _plan_calls(fake_llm) -> int:
    return sum(call.response_model.__name__ == POST_IDEAS for call in fake_llm.calls)


# Planning


async def test_planning_a_split_brief_answers_with_its_ideas_in_posting_order_and_writes_nothing(
    client, ready, fake_llm, split
):
    planned = await _plan(client)

    assert planned["text"] == BRIEF
    assert [(i["whole_brief"], i["posting_order"]) for i in planned["ideas"]] == [
        (True, 1),
        (False, 1),
        (False, 2),
        (False, 3),
    ]
    assert [i["plan"]["core_idea"] for i in planned["ideas"]] == [WHOLE, *CORE_IDEAS]
    assert all(idea["post"] is None for idea in planned["ideas"])
    assert _plan_calls(fake_llm) == 1
    assert len(fake_llm.calls) == 1
    assert await _generations_used(client) == 0
    assert await _read(client, planned["id"]) == planned


async def test_planning_a_brief_with_one_idea_starts_writing_its_post(
    client, ready, fake_llm, background_tasks
):
    fake_llm.replies.append({"post": "The one post.", "first_reply": None})

    planned = await _plan(client)

    [idea] = planned["ideas"]
    assert idea["whole_brief"] is True
    assert idea["post"]["writing_state"] == "writing"
    assert idea["post"]["text"] is None
    await background_tasks.wait()
    post = (await client.get(f"{POSTS}/{idea['post']['id']}")).json()
    assert [part["text"] for part in post["text"]["parts"]] == ["The one post."]
    assert await _generations_used(client) == 1


async def test_planning_is_refused_without_a_positioning(client, subscribed, fake_llm):
    response = await client.post(BRIEFS, json={"brief": BRIEF})

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_the_old_create_post_endpoint_is_gone(client, ready, fake_llm):
    response = await client.post(POSTS, json={"brief": BRIEF})

    assert response.status_code == 405
    assert fake_llm.calls == []


# The hourly cap on plan calls


async def test_plan_calls_are_capped_per_hour_failed_ones_included(
    client, ready, fake_llm, split, monkeypatch, clock, fake_posthog
):
    monkeypatch.setattr("pumpkit.posts.plan_calls.PLAN_CALLS_PER_HOUR", 2)
    await _plan(client)
    fake_llm.standing[POST_IDEAS] = LLMError("provider down")
    assert (await client.post(BRIEFS, json={"brief": BRIEF})).status_code == 502
    fake_llm.calls.clear()

    refused = await client.post(BRIEFS, json={"brief": BRIEF})

    assert refused.status_code == 429
    assert refused.json()["detail"] == "You've planned 2 briefs in the last hour."
    assert fake_llm.calls == []


async def test_a_plan_call_stops_counting_an_hour_later(
    client, ready, fake_llm, split, monkeypatch, clock
):
    monkeypatch.setattr("pumpkit.posts.plan_calls.PLAN_CALLS_PER_HOUR", 1)
    await _plan(client)
    clock.advance(timedelta(hours=1))

    assert (await client.post(BRIEFS, json={"brief": BRIEF})).status_code == 201


# Writing the Ideas picked


async def test_writing_a_subset_of_ideas_writes_one_post_each_and_charges_one_generation_each(
    client, ready, fake_llm, split, background_tasks
):
    planned = await _plan(client)
    first, _, third = _split_ideas(planned)

    response = await _write(client, planned, [first["id"], third["id"]])

    assert response.status_code == 202, response.text
    started = _posts_by_core_idea(response.json())
    assert set(started) == {CORE_IDEAS[0], CORE_IDEAS[2]}
    assert {post["writing_state"] for post in started.values()} == {"writing"}
    await background_tasks.wait()
    brief = await _read(client, planned["id"])
    assert _texts(brief) == {
        CORE_IDEAS[0]: [f"Post on: {CORE_IDEAS[0]}"],
        CORE_IDEAS[2]: [f"Post on: {CORE_IDEAS[2]}"],
    }
    assert {post["writing_state"] for post in _posts_by_core_idea(brief).values()} == {None}
    assert await _generations_used(client) == 2
    assert _plan_calls(fake_llm) == 1


async def test_the_posts_of_one_brief_are_written_at_the_same_time(
    client, ready, fake_llm, split, background_tasks
):
    held = asyncio.Event()
    fake_llm.held[SKETCHED_POST] = held
    planned = await _plan(client)
    ids = [idea["id"] for idea in _split_ideas(planned)]
    assert (await _write(client, planned, ids)).status_code == 202

    def sketching() -> int:
        return sum(call.response_model is SKETCHED_POST for call in fake_llm.calls)

    # Five sketch calls per Post, all three Posts waiting on them at once.
    await asyncio.wait_for(_until(lambda: sketching() == 15), timeout=5)
    brief = await _read(client, planned["id"])

    assert {post["writing_state"] for post in _posts_by_core_idea(brief).values()} == {"writing"}
    held.set()
    await background_tasks.wait()
    assert await _generations_used(client) == 3


async def test_one_post_covering_everything_writes_the_single_post_idea(
    client, ready, fake_llm, split, background_tasks
):
    planned = await _plan(client)

    response = await _write(client, planned, [_whole_idea(planned)["id"]])

    assert response.status_code == 202
    await background_tasks.wait()
    assert _texts(await _read(client, planned["id"])) == {WHOLE: [f"Post on: {WHOLE}"]}
    assert await _generations_used(client) == 1


async def test_a_failed_post_among_successes_charges_nothing_and_shows_not_written(
    client, ready, fake_llm, split, background_tasks, fake_posthog
):
    fake_llm.standing[HUMANIZED_POST] = _humanizer_writing(fails=(CORE_IDEAS[1],))
    planned = await _plan(client)

    await _write(client, planned, [idea["id"] for idea in _split_ideas(planned)])
    await background_tasks.wait()

    posts = _posts_by_core_idea(await _read(client, planned["id"]))
    assert {core_idea: post["writing_state"] for core_idea, post in posts.items()} == {
        CORE_IDEAS[0]: None,
        CORE_IDEAS[1]: "not_written",
        CORE_IDEAS[2]: None,
    }
    assert posts[CORE_IDEAS[1]]["text"] is None
    assert await _generations_used(client) == 2


async def test_too_few_generations_refuses_every_idea_and_starts_none(
    client, ready, fake_llm, split, monkeypatch
):
    monkeypatch.setattr("pumpkit.core.config.settings.GENERATIONS_MONTHLY_CAP", 2)
    planned = await _plan(client)
    fake_llm.calls.clear()

    response = await _write(client, planned, [idea["id"] for idea in _split_ideas(planned)])

    assert response.status_code == 409
    body = response.json()
    assert (body["code"], body["needed"], body["left"]) == ("ALLOWANCE_USED_UP", 3, 2)
    assert body["detail"].startswith("Writing 3 posts needs 3 generations and you have 2 left.")
    assert fake_llm.calls == []
    assert all(idea["post"] is None for idea in (await _read(client, planned["id"]))["ideas"])


async def test_the_hourly_attempt_limit_counts_every_idea_asked_for(
    client, ready, fake_llm, split, monkeypatch
):
    monkeypatch.setattr("pumpkit.posts.version_writing.VERSION_ATTEMPTS_PER_WINDOW", 2)
    planned = await _plan(client)
    first, second, third = _split_ideas(planned)
    assert (await _write(client, planned, [first["id"]])).status_code == 202

    response = await _write(client, planned, [second["id"], third["id"]])

    assert response.status_code == 429
    assert response.json()["detail"] == (
        "Writing 2 posts needs 2 attempts at a version, and you have 1 left of the 2 an hour "
        "allows."
    )
    assert set(_posts_by_core_idea(await _read(client, planned["id"]))) == {CORE_IDEAS[0]}


async def test_an_idea_already_written_is_refused(client, ready, fake_llm, split):
    planned = await _plan(client)
    first = _split_ideas(planned)[0]["id"]
    assert (await _write(client, planned, [first])).status_code == 202

    response = await _write(client, planned, [first])

    assert response.status_code == 409
    assert response.json()["detail"] == "One of these ideas is already written."
    assert response.json()["code"] == "IDEAS_ALREADY_WRITTEN"


async def test_naming_an_idea_twice_writes_it_once(client, ready, fake_llm, split):
    planned = await _plan(client)
    first = _split_ideas(planned)[0]["id"]

    response = await _write(client, planned, [first, first])

    assert response.status_code == 202
    assert len(_posts_by_core_idea(response.json())) == 1
    assert await _generations_used(client) == 1


async def test_an_idea_of_another_brief_is_not_found(client, ready, fake_llm, split):
    planned = await _plan(client)
    other = await _plan(client)

    response = await _write(client, planned, [_split_ideas(other)[0]["id"]])

    assert response.status_code == 404
    assert response.json()["detail"] == "Idea not found."


async def test_writing_no_idea_is_refused_with_a_reason_the_page_can_show(
    client, ready, fake_llm, split
):
    planned = await _plan(client)

    response = await _write(client, planned, [])

    assert response.status_code == 422
    assert response.json()["detail"] == "Pick at least one idea to write."


async def test_the_single_post_idea_with_split_ideas_is_refused_and_writes_nothing(
    client, ready, fake_llm, split
):
    planned = await _plan(client)
    fake_llm.calls.clear()

    response = await _write(
        client, planned, [_whole_idea(planned)["id"], _split_ideas(planned)[0]["id"]]
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Write one post covering everything, or one post per idea, not both."
    )
    assert fake_llm.calls == []
    assert all(idea["post"] is None for idea in (await _read(client, planned["id"]))["ideas"])
    assert await _generations_used(client) == 0


async def test_another_users_brief_is_not_found(
    client, ready, fake_llm, split, sign_in_as_another_subscribed_user
):
    planned = await _plan(client)
    await sign_in_as_another_subscribed_user()

    assert (await client.get(f"{BRIEFS}/{planned['id']}")).status_code == 404
    response = await _write(client, planned, [_split_ideas(planned)[0]["id"]])
    assert response.status_code == 404


# The Generations left, and planning with none


@pytest.fixture
def cap(monkeypatch):
    def _cap(value: int) -> None:
        monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", value)

    return _cap


async def _use_a_generation(db, user_id: str) -> None:
    moment = datetime(2026, 10, 2, tzinfo=timezone.utc)
    post = Post(user_id=user_id, brief="earlier", corpus_post_ids=[], created_at=moment)
    db.add(post)
    await db.flush()
    db.add(
        VersionAttempt(
            post_id=post.id,
            sequence=1,
            version_number=1,
            format="post",
            status="succeeded",
            parts=["earlier"],
            created_at=moment,
        )
    )
    await db.commit()


@dataclass
class _MeanwhilePlanning(FakeLLM):
    """A model that runs `meanwhile` during the plan call, as a concurrent request would."""

    meanwhile: Any = None

    async def structured(self, **kwargs: Any) -> StructuredResult[Any]:
        if kwargs["response_model"].__name__ == POST_IDEAS and self.meanwhile is not None:
            meanwhile, self.meanwhile = self.meanwhile, None
            await meanwhile()
        return await super().structured(**kwargs)


async def test_the_generations_left_count_the_posts_still_being_written(
    client, ready, fake_llm, split, background_tasks, cap, fixed_clock
):
    cap(5)
    held = asyncio.Event()
    fake_llm.held[SKETCHED_POST] = held
    planned = await _plan(client)
    assert planned["generations_left"] == 5
    first, second, _ = _split_ideas(planned)

    written = await _write(client, planned, [first["id"], second["id"]])

    assert written.json()["generations_left"] == 3
    assert (await _read(client, planned["id"]))["generations_left"] == 3
    held.set()
    await background_tasks.wait()
    assert (await _read(client, planned["id"]))["generations_left"] == 3


async def test_with_no_generation_cap_no_generations_left_are_given(
    client, ready, fake_llm, split, monkeypatch
):
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", None)

    assert (await _plan(client))["generations_left"] is None


async def test_with_no_generations_left_a_split_brief_is_still_planned(
    client, db, user, ready, fake_llm, split, cap, fixed_clock
):
    cap(1)
    await _use_a_generation(db, user.id)

    planned = await _plan(client)

    assert planned["generations_left"] == 0
    assert [i["plan"]["core_idea"] for i in _split_ideas(planned)] == CORE_IDEAS
    assert _plan_calls(fake_llm) == 1


async def test_with_no_generations_left_a_brief_with_one_idea_is_planned_and_left_unwritten(
    client, db, user, ready, fake_llm, cap, fixed_clock
):
    cap(1)
    await _use_a_generation(db, user.id)

    planned = await _plan(client)

    [idea] = planned["ideas"]
    assert idea["post"] is None
    assert planned["generations_left"] == 0
    assert len(fake_llm.calls) == 1
    assert await _read(client, planned["id"]) == planned


async def test_the_last_generation_used_during_the_plan_call_leaves_the_brief_unwritten(
    client, db, user, ready, cap, fixed_clock
):
    cap(1)
    llm = _MeanwhilePlanning(
        standing={POST_IDEAS: ideas(), SKETCHED_POST: sketched(), MERGED_SKETCH: merged()},
        replies=[{"post": "final", "first_reply": None}],
    )
    llm.meanwhile = lambda: _use_a_generation(db, user.id)
    app.dependency_overrides[get_llm] = lambda: llm

    planned = await _plan(client)

    [idea] = planned["ideas"]
    assert idea["post"] is None
    assert planned["generations_left"] == 0
    assert [call.response_model.__name__ for call in llm.calls] == [POST_IDEAS]


async def test_the_attempt_limit_reached_during_the_plan_call_leaves_the_brief_unwritten(
    client, ready, fake_llm, split, monkeypatch, fixed_clock
):
    monkeypatch.setattr("pumpkit.posts.version_writing.VERSION_ATTEMPTS_PER_WINDOW", 1)
    planned = await _plan(client)
    llm = _MeanwhilePlanning(standing={**fake_llm.standing, POST_IDEAS: ideas()})

    async def write_the_last_attempt() -> None:
        response = await _write(client, planned, [_split_ideas(planned)[0]["id"]])
        assert response.status_code == 202, response.text

    llm.meanwhile = write_the_last_attempt
    app.dependency_overrides[get_llm] = lambda: llm

    one_idea = await _plan(client, "One idea only.")

    [idea] = one_idea["ideas"]
    assert idea["post"] is None


async def test_planning_is_still_refused_up_front_at_the_attempt_limit(
    client, ready, fake_llm, split, monkeypatch
):
    monkeypatch.setattr("pumpkit.posts.version_writing.VERSION_ATTEMPTS_PER_WINDOW", 1)
    planned = await _plan(client)
    assert (await _write(client, planned, [_split_ideas(planned)[0]["id"]])).status_code == 202
    fake_llm.calls.clear()

    response = await client.post(BRIEFS, json={"brief": BRIEF})

    assert response.status_code == 429
    assert fake_llm.calls == []


async def test_start_post_with_the_last_generation_used_during_the_plan_call_is_refused(
    subscribed, mcp, client, db, user, cap, fixed_clock
):
    await save_positioning(client)
    cap(1)
    llm = _MeanwhilePlanning(standing={POST_IDEAS: ideas()})
    llm.meanwhile = lambda: _use_a_generation(db, user.id)
    app.dependency_overrides[get_llm] = lambda: llm

    result = await mcp.call_tool("start_post", brief=BRIEF)

    assert result["isError"] is True
    assert error_text(result).startswith("You've used this period's 1 generations.")
    assert [call.response_model.__name__ for call in llm.calls] == [POST_IDEAS]


# MCP's start_post, until plan_posts and write_posts replace it


async def test_start_post_over_mcp_writes_one_post_covering_a_split_brief(
    subscribed, mcp, client, fake_llm, split
):
    await save_positioning(client)

    started = await mcp.call_tool("start_post", brief=BRIEF)

    assert not started["isError"], started
    post = (await client.get(f"{POSTS}/{started['structuredContent']['id']}")).json()
    assert post["plan"]["core_idea"] == WHOLE
    assert [part["text"] for part in post["text"]["parts"]] == [f"Post on: {WHOLE}"]
    assert await _generations_used(client) == 1
