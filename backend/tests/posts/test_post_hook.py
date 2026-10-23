"""The hook call on a Post's first Version, seen through the Posts API and the scripted model."""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.core.config import settings
from pumpkit.posts.llm import LLMError
from pumpkit.posts.models import Post
from pumpkit.posts.writing.prompts.draft_post import DRAFT_POST_PROMPT
from pumpkit.posts.writing.prompts.hook import HOOK_PROMPT
from tests.posts.hook_replies import no_hook

AUTHORS = "/api/v1/inspiration-authors"
POSTS = "/api/v1/posts"
DEFAULT_MODEL = "openai/gpt-5.6-luna"
USAGE = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}

HOOK = "Stop shipping big. Ship small."
DRAFT = f"{HOOK}\n\nevery week i ship one tiny thing"

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
    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201


def _hook(hook: str = HOOK, name: str = "stop_x_do_y") -> dict:
    return {"hook_name": name, "hook": hook}


async def _start(client, fake_llm, hook_reply, draft: str = DRAFT) -> dict:
    fake_llm.replies = [hook_reply, {"post": draft}, {"post": "the final"}]
    response = await client.post(POSTS, json={"brief": "ship small things"})
    assert response.status_code == 201, response.text
    return response.json()["versions"][0]


async def _stored_attempt(db):
    result = await db.execute(select(Post).options(selectinload(Post.attempts)))
    [post] = result.scalars()
    [attempt] = post.attempts
    return attempt


def _calls(fake_llm) -> list[str]:
    return [call.response_model.__name__ for call in fake_llm.calls]


def _system(prompt: str) -> dict:
    block = {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    return {"role": "system", "content": [block]}


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


def _hook_message(hook: str) -> dict:
    return _user(
        "Start the post with this hook, exactly as written, on its own line or lines. "
        "Then write the rest of the post so it pays the hook off.\n\n"
        f"<hook>\n{hook}\n</hook>"
    )


async def test_the_hook_call_comes_first_with_the_hook_prompt_the_corpus_and_the_brief(
    client, with_author, fake_llm
):
    await _start(client, fake_llm, _hook())

    assert _calls(fake_llm) == ["written_hook", "drafted_post", "refined_post"]
    hook_call = fake_llm.calls[0]
    assert hook_call.model == DEFAULT_MODEL
    assert hook_call.messages == [
        _system(HOOK_PROMPT),
        _user(LEVELSIO_CORPUS),
        _user(
            "This is the brief the post will be written from. Every fact, number and claim "
            "the hook states must be in it, or in my feedback when I give some.\n\n"
            "<brief>\nship small things\n</brief>"
        ),
    ]


async def test_the_hook_call_uses_the_configured_model(client, with_author, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "LLM_HOOKING_MODEL", "mistral")

    await _start(client, fake_llm, _hook())

    assert fake_llm.calls[0].model == "mistral"


async def test_the_draft_call_is_told_to_start_with_the_hook_last(client, with_author, fake_llm):
    version = await _start(client, fake_llm, _hook())

    assert fake_llm.calls[1].messages == [
        _system(DRAFT_POST_PROMPT),
        _user(LEVELSIO_CORPUS),
        _user("ship small things"),
        _hook_message(HOOK),
    ]
    assert version["draft"] == DRAFT
    assert fake_llm.calls[2].messages[-1] == _user(DRAFT)


async def test_the_version_stores_the_hook_and_the_hook_call(client, db, with_author, fake_llm):
    await _start(client, fake_llm, _hook())

    attempt = await _stored_attempt(db)
    assert (
        attempt.hook_name,
        attempt.hook_text,
        attempt.hook_followed,
        attempt.hooking_model,
        attempt.hooking_usage,
        attempt.hook_answer,
    ) == ("stop_x_do_y", HOOK, True, DEFAULT_MODEL, USAGE, _hook())


async def test_the_hook_is_stripped_of_surrounding_whitespace(client, db, with_author, fake_llm):
    await _start(client, fake_llm, _hook(f"\n {HOOK} \n"))

    assert fake_llm.calls[1].messages[-1] == _hook_message(HOOK)
    assert (await _stored_attempt(db)).hook_text == HOOK


async def test_a_draft_that_does_not_start_with_the_hook_is_kept_and_logged(
    client, db, with_author, fake_llm, caplog
):
    with caplog.at_level(logging.WARNING):
        version = await _start(client, fake_llm, _hook(), draft="every week i ship one tiny thing")

    assert version["draft"] == "every week i ship one tiny thing"
    assert (await _stored_attempt(db)).hook_followed is False
    assert "doesn't start with the Hook" in caplog.text


async def test_the_hook_is_checked_against_the_draft_before_the_scrub(
    client, db, with_author, fake_llm
):
    await _start(
        client, fake_llm, _hook("Ship small—always."), draft="Ship small—always.\n\nthe rest"
    )

    assert (await _stored_attempt(db)).hook_followed is True


async def test_no_hook_leaves_the_draft_call_as_it_was_and_stores_the_call(
    client, db, with_author, fake_llm
):
    await _start(client, fake_llm, no_hook())

    assert fake_llm.calls[1].messages == [
        _system(DRAFT_POST_PROMPT),
        _user(LEVELSIO_CORPUS),
        _user("ship small things"),
    ]
    attempt = await _stored_attempt(db)
    assert (attempt.hook_name, attempt.hook_text, attempt.hook_followed) == (None, None, None)
    assert (attempt.hooking_model, attempt.hook_answer) == (DEFAULT_MODEL, no_hook())


async def test_a_hook_call_that_raises_stores_no_answer(client, db, with_author, fake_llm):
    await _start(client, fake_llm, LLMError("provider down"))

    assert (await _stored_attempt(db)).hook_answer is None


async def test_a_refused_answer_is_stored_though_the_draft_call_gets_no_hook(
    client, db, with_author, fake_llm
):
    reply = _hook(name="made_up")
    await _start(client, fake_llm, dict(reply))

    attempt = await _stored_attempt(db)
    assert (attempt.hook_text, attempt.hooking_model, attempt.hook_answer) == (None, None, reply)


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(LLMError("provider down"), id="the call raises"),
        pytest.param({"mode": "keep"}, id="the answer does not fit the schema"),
        pytest.param(_hook(name="made_up"), id="unknown hook name"),
        pytest.param({"hook_name": None, "hook": HOOK}, id="a hook with no name"),
        pytest.param({"hook_name": "stop_x_do_y", "hook": None}, id="a name with no hook"),
        pytest.param(_hook(" \n "), id="a blank hook"),
        pytest.param(_hook("a" * 3000), id="a hook that leaves no room for the post"),
    ],
)
async def test_a_failed_hook_call_writes_the_version_without_a_hook_and_logs_it(
    client, db, with_author, fake_llm, caplog, reply
):
    with caplog.at_level(logging.WARNING):
        version = await _start(client, fake_llm, reply)

    assert version["final"] == "the final"
    assert fake_llm.calls[1].messages[-1] == _user("ship small things")
    attempt = await _stored_attempt(db)
    assert attempt.status == "succeeded"
    assert (
        attempt.hook_name,
        attempt.hook_text,
        attempt.hook_followed,
        attempt.hooking_model,
        attempt.hooking_usage,
    ) == (None, None, None, None, None)
    assert "Hook call failed" in caplog.text
