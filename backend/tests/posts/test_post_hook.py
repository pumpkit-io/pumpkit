"""The hook step on a Post's first Version, seen through the Posts API and the scripted model."""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.core.config import settings
from pumpkit.posts.llm import LLMError
from pumpkit.posts.models import Post
from pumpkit.posts.writing.prompts.hook import HOOK_PROMPT
from tests.posts.hook_replies import keep_hook

AUTHORS = "/api/v1/inspiration-authors"
POSTS = "/api/v1/posts"
DEFAULT_MODEL = "openai/gpt-5.6-luna"
USAGE = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}

DRAFT = "shipping small beats shipping big\n\nevery week i ship one tiny thing"

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


def _hook(mode: str, hook: str = "", replaced_opening: str = "", name: str = "my_rule") -> dict:
    return {"hook_name": name, "mode": mode, "replaced_opening": replaced_opening, "hook": hook}


async def _start(client, fake_llm, hook_reply) -> dict:
    fake_llm.replies = [{"post": DRAFT}, hook_reply, {"post": "the final"}]
    response = await client.post(POSTS, json={"brief": "ship small things"})
    assert response.status_code == 201, response.text
    return response.json()["versions"][0]


def _humanized_draft(fake_llm) -> str:
    return fake_llm.calls[-1].messages[-1]["content"]


async def _stored_attempt(db):
    result = await db.execute(select(Post).options(selectinload(Post.attempts)))
    [post] = result.scalars()
    [attempt] = post.attempts
    return attempt


def _system(prompt: str) -> dict:
    block = {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    return {"role": "system", "content": [block]}


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


async def test_the_hook_call_gets_the_hook_prompt_the_corpus_the_brief_then_the_draft(
    client, with_author, fake_llm
):
    await _start(client, fake_llm, keep_hook())

    hook_call = fake_llm.calls[1]
    assert hook_call.model == DEFAULT_MODEL
    assert hook_call.response_model.__name__ == "hooked_post"
    assert hook_call.messages == [
        _system(HOOK_PROMPT),
        _user(LEVELSIO_CORPUS),
        _user(
            "This is the brief the post below was written from. Every fact, number and claim "
            "the hook states must be in it or in the post.\n\n"
            "<brief>\nship small things\n</brief>"
        ),
        _user(
            "This is the post to open with a hook. If you replace its opening, copy "
            "replaced_opening from it exactly, character for character.\n\n"
            f"<post>\n{DRAFT}\n</post>"
        ),
    ]


async def test_the_hook_call_uses_the_configured_model(client, with_author, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "LLM_HOOKING_MODEL", "mistral")

    await _start(client, fake_llm, keep_hook())

    assert fake_llm.calls[1].model == "mistral"


async def test_keep_leaves_the_draft_as_it_is_and_stores_the_hook_call(
    client, db, with_author, fake_llm
):
    version = await _start(client, fake_llm, _hook("keep", name="my_rule"))

    assert version["draft"] == DRAFT
    assert _humanized_draft(fake_llm) == DRAFT
    attempt = await _stored_attempt(db)
    assert (attempt.draft, attempt.hook_name, attempt.hooking_model) == (
        DRAFT,
        "my_rule",
        DEFAULT_MODEL,
    )
    assert attempt.hooking_usage == USAGE


async def test_prepend_puts_the_hook_above_the_draft(client, db, with_author, fake_llm):
    version = await _start(
        client, fake_llm, _hook("prepend", hook="I ship one tiny thing a week.", name="my_rule")
    )

    hooked = f"I ship one tiny thing a week.\n\n{DRAFT}"
    assert version["draft"] == hooked
    assert _humanized_draft(fake_llm) == hooked
    attempt = await _stored_attempt(db)
    assert (attempt.draft, attempt.hook_name) == (hooked, "my_rule")


async def test_replace_swaps_the_opening_and_keeps_every_character_after_it(
    client, db, with_author, fake_llm
):
    version = await _start(
        client,
        fake_llm,
        _hook(
            "replace",
            replaced_opening="shipping small beats shipping big",
            hook="Stop shipping big. Ship small.",
            name="stop_x_do_y",
        ),
    )

    hooked = "Stop shipping big. Ship small.\n\nevery week i ship one tiny thing"
    assert version["draft"] == hooked
    assert _humanized_draft(fake_llm) == hooked
    assert (await _stored_attempt(db)).hook_name == "stop_x_do_y"


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(LLMError("provider down"), id="the call raises"),
        pytest.param({"mode": "rewrite"}, id="the answer does not fit the schema"),
        pytest.param(
            _hook("replace", replaced_opening="every week", hook="Ship small."),
            id="the replaced opening is not a prefix",
        ),
        pytest.param(
            _hook("replace", replaced_opening="", hook="Ship small."),
            id="the replaced opening is empty",
        ),
        pytest.param(_hook("prepend", hook="a" * 3000), id="the hooked draft is over the limit"),
        pytest.param(_hook("prepend", hook="Ship small.", name="made_up"), id="unknown hook"),
        pytest.param(_hook("prepend", hook="Ship small.", name="none"), id="none that changes"),
        pytest.param(_hook("prepend", hook="  "), id="a blank hook"),
    ],
)
async def test_a_failed_hook_step_writes_the_version_without_a_hook_and_logs_it(
    client, db, with_author, fake_llm, caplog, reply
):
    with caplog.at_level(logging.WARNING):
        version = await _start(client, fake_llm, reply)

    assert version["draft"] == DRAFT
    assert version["final"] == "the final"
    assert _humanized_draft(fake_llm) == DRAFT
    attempt = await _stored_attempt(db)
    assert attempt.status == "succeeded"
    assert (attempt.hook_name, attempt.hooking_model, attempt.hooking_usage) == (None, None, None)
    assert "Hook step failed" in caplog.text


async def test_a_hooked_draft_of_exactly_the_limit_is_kept(client, with_author, fake_llm):
    hook = "a" * (3000 - len(DRAFT) - 2)

    version = await _start(client, fake_llm, _hook("prepend", hook=hook))

    assert version["draft"] == f"{hook}\n\n{DRAFT}"


async def test_a_feedback_version_makes_no_hook_call(client, db, with_author, fake_llm):
    fake_llm.replies = [{"post": DRAFT}, keep_hook(), {"post": "final 1"}]
    post_id = (await client.post(POSTS, json={"brief": "ship"})).json()["id"]
    fake_llm.calls.clear()
    fake_llm.replies = [{"post": "draft 2"}, {"post": "final 2"}]

    response = await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "shorter"})

    assert response.json()["draft"] == "draft 2"
    assert [call.response_model.__name__ for call in fake_llm.calls] == [
        "revised_post",
        "refined_post",
    ]
    result = await db.execute(select(Post).options(selectinload(Post.attempts)))
    [post] = result.scalars()
    feedback_version = post.attempts[1]
    assert (feedback_version.hook_name, feedback_version.hooking_model) == (None, None)
    assert feedback_version.hooking_usage is None
