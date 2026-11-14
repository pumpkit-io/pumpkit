"""
A Post's first Version is written in a background task (ADR 0026): starting a Post answers once
the Brief is planned, the Post stays in its writing state until the Version is written, and a
write that fails or outlives the timeout shows as not written, with Retry.
"""

import asyncio
from datetime import timedelta

import pytest

from pumpkit.core.llm import LLMError
from pumpkit.posts.writing_state import WRITING_TIMEOUT
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import (
    HUMANIZED_POST,
    PLAN,
    POST_IDEAS,
    SKETCHED_POST,
    started_post_id,
)

POSTS = "/api/v1/posts"
BRIEFS = "/api/v1/briefs"
USAGE = "/api/v1/usage"
BRIEF = "I shipped a pricing page in a weekend and trials went from 12 to 31 a week."


@pytest.fixture
async def ready(client, subscribed):
    await save_positioning(client)


@pytest.fixture
def held(fake_llm):
    """Holds every sketch call until the test sets the event, so a write stays in flight."""
    event = asyncio.Event()
    fake_llm.held[SKETCHED_POST] = event
    return event


async def _start(client, fake_llm, final: str = "The final.") -> str:
    fake_llm.replies.append({"post": final, "first_reply": None})
    response = await client.post(BRIEFS, json={"brief": BRIEF})
    assert response.status_code == 201, response.text
    return started_post_id(response)


async def _post(client, post_id: str) -> dict:
    response = await client.get(f"{POSTS}/{post_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def _generations_used(client) -> int:
    return (await client.get(USAGE)).json()["allowance"]["generations"]["used"]


def _plan_calls(fake_llm) -> int:
    return sum(call.response_model.__name__ == POST_IDEAS for call in fake_llm.calls)


async def test_planning_a_brief_answers_with_its_post_being_written_before_its_version_is(
    client, ready, fake_llm, background_tasks, held
):
    fake_llm.replies.append({"post": "The final.", "first_reply": None})

    response = await client.post(BRIEFS, json={"brief": BRIEF})

    assert response.status_code == 201
    body = response.json()
    assert body["text"] == BRIEF
    [idea] = body["ideas"]
    assert idea["plan"] == PLAN
    assert idea["post"]["writing_state"] == "writing"
    assert idea["post"]["text"] is None
    post = await _post(client, idea["post"]["id"])
    assert post["brief"] == BRIEF
    assert post["writing_state"] == "writing"
    assert post["status"] is None
    assert post["text"] is None
    assert post["versions"] == []


async def test_the_version_becomes_the_text_once_the_task_ends(
    client, ready, fake_llm, background_tasks
):
    post_id = await _start(client, fake_llm, final="Trials went from 12 to 31 a week.")

    await background_tasks.wait()

    post = await _post(client, post_id)
    assert post["writing_state"] is None
    assert post["status"] == "draft"
    assert [part["text"] for part in post["text"]["parts"]] == ["Trials went from 12 to 31 a week."]
    assert [version["number"] for version in post["versions"]] == [1]


async def test_a_post_being_written_is_not_a_draft_and_is_not_listed(
    client, ready, fake_llm, background_tasks, held
):
    await _start(client, fake_llm)

    listed = (await client.get(POSTS)).json()
    drafts = (await client.get(POSTS, params={"status": "draft"})).json()

    assert listed["data"] == []
    assert drafts["data"] == []
    assert listed["counts"]["draft"] == 0


async def test_the_generation_is_charged_when_the_version_is_written(
    client, ready, fake_llm, background_tasks, held
):
    await _start(client, fake_llm)
    assert await _generations_used(client) == 0

    held.set()
    await background_tasks.wait()

    assert await _generations_used(client) == 1


async def test_a_failed_write_charges_nothing_and_shows_the_post_not_written(
    client, ready, fake_llm, background_tasks, fake_posthog
):
    fake_llm.standing[HUMANIZED_POST] = LLMError("provider down")
    response = await client.post(BRIEFS, json={"brief": BRIEF})
    assert response.status_code == 201

    await background_tasks.wait()

    post = await _post(client, started_post_id(response))
    assert post["writing_state"] == "not_written"
    assert post["status"] is None
    assert post["text"] is None
    assert await _generations_used(client) == 0
    fake_posthog.capture_exception.assert_called_once()


async def test_a_write_older_than_the_timeout_shows_the_post_not_written(
    client, ready, fake_llm, background_tasks, held, clock
):
    post_id = await _start(client, fake_llm)

    clock.advance(timedelta(minutes=15) - timedelta(seconds=1))
    assert (await _post(client, post_id))["writing_state"] == "writing"
    clock.advance(timedelta(seconds=1))
    assert (await _post(client, post_id))["writing_state"] == "not_written"


async def test_a_write_that_ends_after_the_timeout_records_nothing(
    client, ready, fake_llm, background_tasks, held, clock
):
    post_id = await _start(client, fake_llm)
    clock.advance(WRITING_TIMEOUT)

    held.set()
    await background_tasks.wait()

    post = await _post(client, post_id)
    assert post["writing_state"] == "not_written"
    assert post["text"] is None
    assert await _generations_used(client) == 0


async def test_retry_writes_the_post_again_from_its_plan_without_planning(
    client, ready, fake_llm, background_tasks
):
    fake_llm.standing[HUMANIZED_POST] = LLMError("provider down")
    post_id = started_post_id(await client.post(BRIEFS, json={"brief": BRIEF}))
    await background_tasks.wait()
    del fake_llm.standing[HUMANIZED_POST]
    fake_llm.replies.append({"post": "Written on retry.", "first_reply": None})
    fake_llm.calls.clear()

    response = await client.post(f"{POSTS}/{post_id}/retry")

    assert response.status_code == 202
    assert response.json()["writing_state"] == "writing"
    await background_tasks.wait()
    post = await _post(client, post_id)
    assert [part["text"] for part in post["text"]["parts"]] == ["Written on retry."]
    assert post["plan"] == PLAN
    assert _plan_calls(fake_llm) == 0
    assert await _generations_used(client) == 1


async def test_retry_after_the_timeout_keeps_only_the_retried_write(
    client, ready, fake_llm, background_tasks, held, clock
):
    fake_llm.replies.append({"post": "From the lost write.", "first_reply": None})
    post_id = started_post_id(await client.post(BRIEFS, json={"brief": BRIEF}))
    clock.advance(WRITING_TIMEOUT)
    fake_llm.replies.append({"post": "From the retry.", "first_reply": None})

    assert (await client.post(f"{POSTS}/{post_id}/retry")).status_code == 202
    held.set()
    await background_tasks.wait()

    post = await _post(client, post_id)
    assert [version["number"] for version in post["versions"]] == [1]
    assert await _generations_used(client) == 1


@pytest.mark.parametrize("state", ["writing", "written"])
async def test_retry_is_refused_unless_the_post_is_not_written(
    client, ready, fake_llm, background_tasks, held, state
):
    post_id = await _start(client, fake_llm)
    if state == "written":
        held.set()
        await background_tasks.wait()

    response = await client.post(f"{POSTS}/{post_id}/retry")

    assert response.status_code == 409


async def test_retry_counts_as_a_new_attempt_against_the_hourly_limit(
    client, ready, fake_llm, background_tasks, monkeypatch
):
    monkeypatch.setattr("pumpkit.posts.version_writing.VERSION_ATTEMPTS_PER_WINDOW", 2)
    fake_llm.standing[HUMANIZED_POST] = LLMError("provider down")
    post_id = started_post_id(await client.post(BRIEFS, json={"brief": BRIEF}))
    await background_tasks.wait()
    assert (await client.post(f"{POSTS}/{post_id}/retry")).status_code == 202
    await background_tasks.wait()

    response = await client.post(f"{POSTS}/{post_id}/retry")

    assert response.status_code == 429


async def test_writes_in_flight_count_against_the_hourly_limit(
    client, ready, fake_llm, background_tasks, held, monkeypatch
):
    monkeypatch.setattr("pumpkit.posts.version_writing.VERSION_ATTEMPTS_PER_WINDOW", 1)
    await _start(client, fake_llm)

    response = await client.post(BRIEFS, json={"brief": BRIEF})

    assert response.status_code == 429


async def test_writes_in_flight_hold_their_generations(
    client, ready, fake_llm, background_tasks, held, monkeypatch
):
    monkeypatch.setattr("pumpkit.core.config.settings.GENERATIONS_MONTHLY_CAP", 1)
    await _start(client, fake_llm)

    response = await client.post(BRIEFS, json={"brief": BRIEF})

    assert response.status_code == 201
    assert response.json()["generations_left"] == 0
    assert [idea["post"] for idea in response.json()["ideas"]] == [None]


async def test_get_post_over_mcp_reports_a_post_still_being_written(
    subscribed, mcp, client, fake_llm, background_tasks, held
):
    await save_positioning(client)
    fake_llm.replies.append({"post": "The final.", "first_reply": None})
    started = await mcp.call_tool("start_post", brief=BRIEF)
    assert not started["isError"], started
    post_id = started["structuredContent"]["id"]
    assert started["structuredContent"]["writing_state"] == "writing"

    result = await mcp.call_tool("get_post", post_id=post_id)

    assert result["structuredContent"]["writing_state"] == "writing"
    assert result["structuredContent"]["status"] is None
    held.set()
    await background_tasks.wait()
    done = await mcp.call_tool("get_post", post_id=post_id)
    assert done["structuredContent"]["writing_state"] is None
    assert done["structuredContent"]["status"] == "draft"


async def test_feedback_waits_for_the_first_version(
    client, ready, fake_llm, background_tasks, held
):
    post_id = await _start(client, fake_llm)

    response = await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "shorter"})

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Pumpkit is still writing this post's first version. Give feedback once it's written."
    )
