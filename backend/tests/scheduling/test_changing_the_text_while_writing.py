"""
While Feedback's Version is being written, the Post's Text doesn't change: an edit, a restore
or more Feedback is refused, so the new Version, which becomes the Text, can't overwrite them.
"""

from datetime import datetime, timedelta, timezone

import pytest

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.main import app
from pumpkit.posts.llm import FakeLLM, LLMError, get_llm
from tests.mcp_client import error_text
from tests.posts.writing_replies import written

POSTS = "/api/v1/posts"
BEING_WRITTEN = "Pumpkit is writing a new Version of this Post. Try again once it's written."


@pytest.fixture
async def post(client, subscribed, fake_x_reader, fake_llm, fixed_clock, connect_x) -> dict:
    """A Post with two Versions, so its Text is Version 2 and Version 1 can be restored."""
    await connect_x()
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    added = await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    assert added.status_code == 201, added.text
    fake_llm.replies = [written("sketch one"), {"post": "Version one."}]
    started = await client.post(POSTS, json={"brief": "ship small things"})
    assert started.status_code == 201, started.text
    fake_llm.replies = [written("sketch two"), {"post": "Version two."}]
    given = await client.post(f"{POSTS}/{started.json()['id']}/versions", json={"feedback": "more"})
    assert given.status_code == 201, given.text
    return started.json()


def _llm_that_meanwhile(change, *replies) -> list:
    """Make the next Feedback call `change()` during its first model call; returns its answers."""
    answers: list = []

    class MeanwhileLLM(FakeLLM):
        async def structured(self, **kwargs):
            if not answers:
                answers.append(await change())
            return await super().structured(**kwargs)

    app.dependency_overrides[get_llm] = lambda: MeanwhileLLM(replies=list(replies))
    return answers


def _written_next() -> list:
    return [written("sketch three"), {"post": "Version three."}]


async def _text_of(client, post_id: str) -> dict:
    return (await client.get(f"{POSTS}/{post_id}")).json()["text"]


async def test_a_save_while_feedback_is_written_is_refused_and_the_version_becomes_the_text(
    client, post, mcp
):
    answers = _llm_that_meanwhile(
        lambda: client.put(f"{POSTS}/{post['id']}/text", json={"parts": ["Typed meanwhile."]}),
        *_written_next(),
    )

    result = await mcp.call_tool("give_feedback", post_id=post["id"], feedback="shorter")

    assert result["isError"] is False, result
    assert answers[0].status_code == 409
    assert answers[0].json()["detail"] == BEING_WRITTEN
    text = await _text_of(client, post["id"])
    assert [p["text"] for p in text["parts"]] == ["Version three."]
    assert text["version_number"] == 3


async def test_a_restore_while_feedback_is_written_is_refused(client, post):
    answers = _llm_that_meanwhile(
        lambda: client.post(f"{POSTS}/{post['id']}/versions/1/restore"), *_written_next()
    )

    response = await client.post(f"{POSTS}/{post['id']}/versions", json={"feedback": "shorter"})

    assert response.status_code == 201, response.text
    assert answers[0].status_code == 409
    assert answers[0].json()["detail"] == BEING_WRITTEN
    assert (await _text_of(client, post["id"]))["version_number"] == 3


async def test_the_restore_version_tool_refuses_while_feedback_is_written(client, post, mcp):
    answers = _llm_that_meanwhile(
        lambda: mcp.call_tool("restore_version", post_id=post["id"], version_number=1),
        *_written_next(),
    )

    response = await client.post(f"{POSTS}/{post['id']}/versions", json={"feedback": "shorter"})

    assert response.status_code == 201, response.text
    assert error_text(answers[0]) == BEING_WRITTEN


async def test_more_feedback_while_feedback_is_written_is_refused(client, post):
    answers = _llm_that_meanwhile(
        lambda: client.post(f"{POSTS}/{post['id']}/versions", json={"feedback": "longer"}),
        *_written_next(),
    )

    response = await client.post(f"{POSTS}/{post['id']}/versions", json={"feedback": "shorter"})

    assert response.status_code == 201, response.text
    assert answers[0].status_code == 409
    assert answers[0].json()["detail"] == BEING_WRITTEN
    versions = (await client.get(f"{POSTS}/{post['id']}")).json()["versions"]
    assert [v["feedback"] for v in versions] == [None, "more", "shorter"]


async def test_the_text_changes_again_once_a_write_fails(client, post):
    app.dependency_overrides[get_llm] = lambda: FakeLLM(replies=[LLMError("down")])
    failed = await client.post(f"{POSTS}/{post['id']}/versions", json={"feedback": "shorter"})

    response = await client.put(f"{POSTS}/{post['id']}/text", json={"parts": ["Typed after."]})

    assert failed.status_code >= 500
    assert response.status_code == 200, response.text


async def test_a_write_running_past_its_time_stops_holding_the_text(client, post, fixed_clock):
    async def save_much_later():
        fixed_clock.advance(timedelta(hours=1))
        return await client.put(f"{POSTS}/{post['id']}/text", json={"parts": ["Typed later."]})

    answers = _llm_that_meanwhile(save_much_later, *_written_next())

    await client.post(f"{POSTS}/{post['id']}/versions", json={"feedback": "shorter"})

    assert answers[0].status_code == 200, answers[0].text
