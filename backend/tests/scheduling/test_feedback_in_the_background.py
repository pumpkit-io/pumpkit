"""
Feedback's Version is written in a background task, as a first Version is (ADR 0026): the Feedback
request answers with the Post being written, the Text stays as it was until the Version replaces
it, and a write that fails, outlives the timeout or was superseded leaves the Text alone.
"""

import asyncio
from datetime import timedelta

import pytest

from pumpkit.core.llm import LLMError
from pumpkit.posts.writing_state import WRITING_TIMEOUT
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import HUMANIZED_POST, REVISED_POST, started_post_id

POSTS = "/api/v1/posts"
BRIEFS = "/api/v1/briefs"
USAGE = "/api/v1/usage"


@pytest.fixture
async def post_id(client, subscribed, fake_llm, background_tasks, clock) -> str:
    """A Draft whose Text is Version 1, "Version one.", written in the background."""
    await save_positioning(client)
    fake_llm.replies.append({"post": "Version one.", "first_reply": None})
    started = await client.post(BRIEFS, json={"brief": "ship small things"})
    assert started.status_code == 201, started.text
    await background_tasks.wait()
    return started_post_id(started)


@pytest.fixture
def revising(fake_llm) -> asyncio.Event:
    """Holds every revise call until the test sets the event, so a Feedback stays in flight."""
    event = asyncio.Event()
    fake_llm.held[REVISED_POST] = event
    return event


async def _post(client, post_id: str) -> dict:
    response = await client.get(f"{POSTS}/{post_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _texts(post: dict) -> list[str]:
    return [part["text"] for part in post["text"]["parts"]]


async def _generations_used(client) -> int:
    return (await client.get(USAGE)).json()["allowance"]["generations"]["used"]


async def _feedback(client, post_id: str, feedback: str = "shorter"):
    return await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": feedback})


async def test_feedback_answers_with_the_post_being_written_before_its_version_is(
    client, post_id, fake_llm, revising
):
    fake_llm.replies.append({"post": "Version two.", "first_reply": None})

    response = await _feedback(client, post_id)

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["id"] == post_id
    assert body["writing_state"] == "writing"
    assert body["status"] == "draft"
    assert [version["number"] for version in body["versions"]] == [1]
    post = await _post(client, post_id)
    assert post["writing_state"] == "writing"
    assert post["status"] == "draft"
    assert _texts(post) == ["Version one."]


async def test_the_version_becomes_the_text_and_is_charged_once_the_task_ends(
    client, post_id, fake_llm, background_tasks, revising
):
    fake_llm.replies.append({"post": "Version two.", "first_reply": None})
    assert (await _feedback(client, post_id)).status_code == 202
    assert await _generations_used(client) == 1

    revising.set()
    await background_tasks.wait()

    post = await _post(client, post_id)
    assert post["writing_state"] is None
    assert _texts(post) == ["Version two."]
    assert post["text"]["version_number"] == 2
    assert [v["feedback"] for v in post["versions"]] == [None, "shorter"]
    assert await _generations_used(client) == 2


async def test_a_failed_feedback_leaves_the_text_as_it_was_and_charges_nothing(
    client, post_id, fake_llm, background_tasks, fake_posthog
):
    fake_llm.standing[HUMANIZED_POST] = LLMError("provider down")

    assert (await _feedback(client, post_id)).status_code == 202
    await background_tasks.wait()

    post = await _post(client, post_id)
    assert post["writing_state"] is None
    assert _texts(post) == ["Version one."]
    assert post["text"]["version_number"] == 1
    assert [version["number"] for version in post["versions"]] == [1]
    assert await _generations_used(client) == 1
    fake_posthog.capture_exception.assert_called_once()


async def test_the_text_changes_again_once_a_feedback_fails(
    client, post_id, fake_llm, background_tasks
):
    fake_llm.standing[HUMANIZED_POST] = LLMError("provider down")
    await _feedback(client, post_id)
    await background_tasks.wait()

    response = await client.put(f"{POSTS}/{post_id}/text", json={"parts": ["Typed after."]})

    assert response.status_code == 200, response.text


async def test_a_feedback_older_than_the_timeout_is_no_longer_being_written(
    client, post_id, fake_llm, revising, clock
):
    await _feedback(client, post_id)

    clock.advance(WRITING_TIMEOUT - timedelta(seconds=1))
    assert (await _post(client, post_id))["writing_state"] == "writing"
    clock.advance(timedelta(seconds=1))
    post = await _post(client, post_id)
    assert post["writing_state"] is None
    assert _texts(post) == ["Version one."]


async def test_a_feedback_that_ends_after_the_timeout_records_nothing(
    client, post_id, fake_llm, background_tasks, revising, clock
):
    fake_llm.replies.append({"post": "From the late write.", "first_reply": None})
    await _feedback(client, post_id)
    clock.advance(WRITING_TIMEOUT)

    revising.set()
    await background_tasks.wait()

    post = await _post(client, post_id)
    assert _texts(post) == ["Version one."]
    assert [version["number"] for version in post["versions"]] == [1]
    assert await _generations_used(client) == 1


async def test_a_feedback_superseded_by_an_edit_after_the_timeout_records_nothing(
    client, post_id, fake_llm, background_tasks, revising, clock
):
    fake_llm.replies.append({"post": "From the lost write.", "first_reply": None})
    await _feedback(client, post_id)
    clock.advance(WRITING_TIMEOUT)
    edited = await client.put(f"{POSTS}/{post_id}/text", json={"parts": ["Typed later."]})
    assert edited.status_code == 200, edited.text

    revising.set()
    await background_tasks.wait()

    post = await _post(client, post_id)
    assert _texts(post) == ["Typed later."]
    assert [version["number"] for version in post["versions"]] == [1]
    assert await _generations_used(client) == 1


async def test_a_feedback_superseded_by_a_restore_after_the_timeout_records_nothing(
    client, post_id, fake_llm, background_tasks, revising, clock
):
    fake_llm.replies.append({"post": "From the lost write.", "first_reply": None})
    await _feedback(client, post_id)
    clock.advance(WRITING_TIMEOUT)
    restored = await client.post(f"{POSTS}/{post_id}/versions/1/restore")
    assert restored.status_code == 200, restored.text

    revising.set()
    await background_tasks.wait()

    post = await _post(client, post_id)
    assert _texts(post) == ["Version one."]
    assert [version["number"] for version in post["versions"]] == [1]
    assert await _generations_used(client) == 1


async def test_a_feedback_superseded_by_more_feedback_after_the_timeout_records_only_the_later(
    client, post_id, fake_llm, background_tasks, revising, clock
):
    fake_llm.standing[HUMANIZED_POST] = lambda call: {"post": "Rewritten.", "first_reply": None}
    await _feedback(client, post_id, "shorter")
    clock.advance(WRITING_TIMEOUT)
    assert (await _feedback(client, post_id, "warmer")).status_code == 202

    revising.set()
    await background_tasks.wait()

    post = await _post(client, post_id)
    assert [v["feedback"] for v in post["versions"]] == [None, "warmer"]
    assert await _generations_used(client) == 2


async def test_a_feedback_being_written_holds_its_generation(
    client, post_id, fake_llm, revising, monkeypatch
):
    monkeypatch.setattr("pumpkit.core.config.settings.GENERATIONS_MONTHLY_CAP", 2)
    await _feedback(client, post_id)

    response = await client.post(BRIEFS, json={"brief": "ship small things"})

    assert response.status_code == 409
    assert response.json()["left"] == 0


async def test_give_feedback_over_mcp_answers_that_the_version_is_being_written(
    client, post_id, fake_llm, background_tasks, revising, mcp
):
    fake_llm.replies.append({"post": "Version two.", "first_reply": None})

    given = await mcp.call_tool("give_feedback", post_id=post_id, feedback="shorter")

    assert given["isError"] is False, given
    assert given["structuredContent"]["writing_state"] == "writing"
    assert given["structuredContent"]["id"] == post_id
    writing = await mcp.call_tool("get_post", post_id=post_id)
    assert writing["structuredContent"]["writing_state"] == "writing"
    revising.set()
    await background_tasks.wait()
    done = await mcp.call_tool("get_post", post_id=post_id)
    assert done["structuredContent"]["writing_state"] is None
    assert [v["number"] for v in done["structuredContent"]["versions"]] == [1, 2]


async def test_a_failed_feedback_shows_on_the_post_until_the_user_moves_on(
    client, post_id, fake_llm, background_tasks
):
    fake_llm.standing[HUMANIZED_POST] = LLMError("provider down")
    response = await client.post(
        f"{POSTS}/{post_id}/versions", json={"feedback": "make it a thread", "format": "thread"}
    )
    assert response.status_code == 202, response.text
    assert response.json()["failed_feedback"] is None

    await background_tasks.wait()

    post = await _post(client, post_id)
    assert post["failed_feedback"] == {"feedback": "make it a thread", "format": "thread"}


async def test_a_feedback_that_outlived_the_timeout_shows_as_failed(
    client, post_id, fake_llm, revising, clock
):
    await _feedback(client, post_id, "warmer")
    assert (await _post(client, post_id))["failed_feedback"] is None

    clock.advance(WRITING_TIMEOUT)

    post = await _post(client, post_id)
    assert post["failed_feedback"] == {"feedback": "warmer", "format": "post"}


async def test_a_written_feedback_leaves_no_failure(client, post_id, fake_llm, background_tasks):
    fake_llm.standing[HUMANIZED_POST] = LLMError("provider down")
    await _feedback(client, post_id)
    await background_tasks.wait()
    fake_llm.standing.pop(HUMANIZED_POST)
    fake_llm.replies.append({"post": "Version two.", "first_reply": None})

    await _feedback(client, post_id, "warmer")
    await background_tasks.wait()

    post = await _post(client, post_id)
    assert _texts(post) == ["Version two."]
    assert post["failed_feedback"] is None


@pytest.mark.parametrize(
    "move_on",
    [
        lambda client, post_id: client.put(f"{POSTS}/{post_id}/text", json={"parts": ["Typed."]}),
        lambda client, post_id: client.post(f"{POSTS}/{post_id}/versions/1/restore"),
        lambda client, post_id: client.delete(f"{POSTS}/{post_id}/failed-feedback"),
    ],
    ids=["edit", "restore", "dismiss"],
)
async def test_a_failed_feedback_goes_once_the_user_edits_restores_or_dismisses_it(
    client, post_id, fake_llm, background_tasks, move_on
):
    fake_llm.standing[HUMANIZED_POST] = LLMError("provider down")
    await _feedback(client, post_id)
    await background_tasks.wait()

    response = await move_on(client, post_id)

    assert response.status_code in (200, 204), response.text
    assert (await _post(client, post_id))["failed_feedback"] is None


async def test_dismissing_leaves_a_feedback_being_written_alone(
    client, post_id, fake_llm, background_tasks, revising, clock
):
    fake_llm.replies.append({"post": "Version two.", "first_reply": None})
    await _feedback(client, post_id, "warmer")

    response = await client.delete(f"{POSTS}/{post_id}/failed-feedback")
    assert response.status_code == 204, response.text
    clock.advance(WRITING_TIMEOUT)

    post = await _post(client, post_id)
    assert post["failed_feedback"] == {"feedback": "warmer", "format": "post"}


async def test_dismissing_another_users_post_is_not_found(
    client, post_id, sign_in_as_another_subscribed_user
):
    await sign_in_as_another_subscribed_user()

    response = await client.delete(f"{POSTS}/{post_id}/failed-feedback")

    assert response.status_code == 404


async def test_get_post_over_mcp_reports_the_failed_feedback(
    client, post_id, fake_llm, background_tasks, mcp
):
    fake_llm.standing[HUMANIZED_POST] = LLMError("provider down")
    await mcp.call_tool("give_feedback", post_id=post_id, feedback="shorter")
    await background_tasks.wait()

    read = await mcp.call_tool("get_post", post_id=post_id)

    assert read["structuredContent"]["failed_feedback"] == {"feedback": "shorter", "format": "post"}


async def test_a_feedback_that_fails_while_being_recorded_is_recorded_as_failed(
    client, post_id, fake_llm, background_tasks, fake_posthog, monkeypatch
):
    broken = RuntimeError("database hiccup")

    async def charge_fails(*args, **kwargs):
        raise broken

    monkeypatch.setattr("pumpkit.posts.version_writing.charge_generation", charge_fails)
    fake_llm.replies.append({"post": "Version two.", "first_reply": None})

    await _feedback(client, post_id, "warmer")
    await background_tasks.wait()

    post = await _post(client, post_id)
    assert post["writing_state"] is None
    assert _texts(post) == ["Version one."]
    assert [version["number"] for version in post["versions"]] == [1]
    assert post["failed_feedback"] == {"feedback": "warmer", "format": "post"}
    assert await _generations_used(client) == 1
    assert fake_posthog.capture_exception.call_args_list[0].args[0] is broken


async def test_a_feedback_reports_its_error_even_when_recording_the_failure_fails(
    client, post_id, fake_llm, background_tasks, fake_posthog, monkeypatch
):
    async def recording_fails(*args, **kwargs):
        raise RuntimeError("database gone")

    monkeypatch.setattr("pumpkit.posts.version_writing.record_failed_attempt", recording_fails)
    down = LLMError("provider down")
    fake_llm.standing[HUMANIZED_POST] = down

    await _feedback(client, post_id)
    await background_tasks.wait()

    reported = [call.args[0] for call in fake_posthog.capture_exception.call_args_list]
    assert down in reported
