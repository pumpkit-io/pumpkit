"""
The library Hook, chosen and written by a Thread's sketch call and by the revision call, seen
through the Posts API and the scripted model. A single post's first Version has none.
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.posts.models import Post
from pumpkit.posts.writing.prompts.sketch_thread import sketch_thread_prompt
from pumpkit.x_connection.x_length import X_POST_MAX_CHARS
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import REASONING, writing_calls, written, written_thread

AUTHORS = "/api/v1/inspiration-authors"
POSTS = "/api/v1/posts"

HOOK_REASONING = "The brief states a rule for shipping, so stop_x_do_y fits."
SKETCH = "Stop shipping big. Ship small.\n\nevery week i ship one tiny thing"

LEVELSIO_CORPUS = (
    "Below are real posts by the writers whose voice you are reproducing, grouped by author. "
    "They are examples of HOW to write, never of what to write about.\n\n"
    '<creator handle="levelsio">\n'
    "<post>levelsio post 0</post>\n"
    "</creator>"
)


@pytest.fixture
async def with_author(client, subscribed, fake_x_reader):
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post 0",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc) - timedelta(hours=1),
        )
    ]
    await save_positioning(client)
    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201


async def _start(client, fake_llm, reply: dict) -> dict:
    """A Thread, whose first Version is still written with the library Hook."""
    fake_llm.replies = [reply, {"parts": ["the final", "part two"]}]
    response = await client.post(POSTS, json={"brief": "ship small things", "format": "thread"})
    assert response.status_code == 201, response.text
    return response.json()


async def _attempts(db):
    result = await db.execute(select(Post).options(selectinload(Post.attempts)))
    [post] = result.scalars()
    return sorted(post.attempts, key=lambda attempt: attempt.created_at)


def _thread(sketch: str, hook_name=None, hook_reasoning=REASONING) -> dict:
    return written_thread([sketch, "part two"], hook_name, hook_reasoning)


def _system(prompt: str) -> dict:
    block = {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    return {"role": "system", "content": [block]}


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


async def test_the_first_version_writes_the_hook_in_the_sketch_call_then_humanizes(
    client, with_author, fake_llm
):
    await _start(client, fake_llm, _thread(SKETCH, "stop_x_do_y", HOOK_REASONING))

    sketch_call, humanizer_call = writing_calls(fake_llm)
    assert (sketch_call.response_model.__name__, humanizer_call.response_model.__name__) == (
        "drafted_thread",
        "refined_thread",
    )
    assert sketch_call.messages == [
        _system(sketch_thread_prompt(X_POST_MAX_CHARS)),
        _user(LEVELSIO_CORPUS),
        _user("ship small things"),
    ]
    assert humanizer_call.messages[-1] == _user(
        f'<part number="1">\n{SKETCH}\n</part>\n\n<part number="2">\npart two\n</part>'
    )


async def test_the_version_stores_the_hook_reasoning_and_the_library_hook(
    client, db, with_author, fake_llm
):
    await _start(client, fake_llm, _thread(SKETCH, "stop_x_do_y", HOOK_REASONING))

    [attempt] = await _attempts(db)
    assert (attempt.hook_reasoning, attempt.hook_name) == (HOOK_REASONING, "stop_x_do_y")


async def test_an_opening_with_no_library_hook_stores_its_reasoning_and_no_name(
    client, db, with_author, fake_llm
):
    await _start(client, fake_llm, _thread("every week i ship one tiny thing"))

    [attempt] = await _attempts(db)
    assert attempt.hook_name is None
    assert attempt.hook_reasoning == written("")["hook_reasoning"]


async def test_an_unknown_hook_name_is_logged_and_stored_as_none(
    client, db, with_author, fake_llm, caplog
):
    with caplog.at_level(logging.WARNING):
        version = (await _start(client, fake_llm, _thread(SKETCH, "made_up", HOOK_REASONING)))[
            "versions"
        ][0]

    assert version["parts"][0]["text"] == "the final"
    [attempt] = await _attempts(db)
    assert (attempt.status, attempt.hook_name) == ("succeeded", None)
    assert attempt.hook_reasoning == HOOK_REASONING
    assert "made_up" in caplog.text


async def test_a_feedback_version_stores_the_revision_calls_hook_without_a_classifier_question(
    client, db, with_author, fake_llm, fake_classifier
):
    fake_llm.replies = [{"post": "the final"}]
    started = await client.post(POSTS, json={"brief": "ship small things"})
    post_id = started.json()["id"]
    fake_llm.calls.clear()
    fake_llm.replies = [written(SKETCH, "stop_x_do_y", HOOK_REASONING), {"post": "final 2"}]

    response = await client.post(
        f"{POSTS}/{post_id}/versions", json={"feedback": "open with a rule"}
    )

    assert response.status_code == 201, response.text
    assert [call.response_model.__name__ for call in fake_llm.calls] == [
        "revised_post",
        "refined_post",
    ]
    assert fake_classifier.calls == []
    second = (await _attempts(db))[1]
    assert (second.hook_reasoning, second.hook_name, second.sketch_parts) == (
        HOOK_REASONING,
        "stop_x_do_y",
        [SKETCH],
    )
