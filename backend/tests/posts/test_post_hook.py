"""The hook step on a Post's first Version, seen through the Posts API and the scripted model."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

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


def _hook(
    mode: str,
    replaced_text: Optional[str] = None,
    replacing_text: Optional[str] = None,
    replacing: Optional[str] = "my_rule",
    current: Optional[str] = None,
) -> dict:
    return {
        "current_hook_name": current,
        "mode": mode,
        "replacing_hook_name": replacing,
        "replaced_text": replaced_text,
        "replacing_text": replacing_text,
    }


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
            "replaced_text from its start exactly, character for character, and end "
            "replacing_text with the same lines you carry, copied exactly.\n\n"
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
    version = await _start(client, fake_llm, _hook("keep", replacing=None, current="my_rule"))

    assert version["draft"] == DRAFT
    assert _humanized_draft(fake_llm) == DRAFT
    attempt = await _stored_attempt(db)
    assert (
        attempt.draft,
        attempt.current_hook_name,
        attempt.replacing_hook_name,
        attempt.hooking_model,
    ) == (DRAFT, "my_rule", None, DEFAULT_MODEL)
    assert attempt.hooking_usage == USAGE


async def test_replace_swaps_the_opening_and_keeps_every_character_after_it(
    client, db, with_author, fake_llm
):
    version = await _start(
        client,
        fake_llm,
        _hook(
            "replace",
            replaced_text=DRAFT,
            replacing_text="Stop shipping big. Ship small.\n\nevery week i ship one tiny thing",
            replacing="stop_x_do_y",
        ),
    )

    hooked = "Stop shipping big. Ship small.\n\nevery week i ship one tiny thing"
    assert version["draft"] == hooked
    assert _humanized_draft(fake_llm) == hooked
    attempt = await _stored_attempt(db)
    assert (attempt.current_hook_name, attempt.replacing_hook_name) == (None, "stop_x_do_y")


async def test_replace_keeps_the_draft_after_the_replaced_text(client, with_author, fake_llm):
    draft = "line one\n\nline two\n\nline three"
    fake_llm.replies = [
        {"post": draft},
        _hook("replace", replaced_text="line one\n\nline two", replacing_text="Hook.\nline two"),
        {"post": "the final"},
    ]
    response = await client.post(POSTS, json={"brief": "ship small things"})

    assert response.json()["versions"][0]["draft"] == "Hook.\nline two\n\nline three"


async def test_replace_with_nothing_removed_puts_the_hook_above_the_draft(
    client, db, with_author, fake_llm
):
    version = await _start(
        client,
        fake_llm,
        _hook(
            "replace",
            replaced_text="shipping small beats shipping big",
            replacing_text="I ship one tiny thing a week.\n\nshipping small beats shipping big",
        ),
    )

    hooked = f"I ship one tiny thing a week.\n\n{DRAFT}"
    assert version["draft"] == hooked
    assert _humanized_draft(fake_llm) == hooked
    attempt = await _stored_attempt(db)
    assert (attempt.draft, attempt.current_hook_name, attempt.replacing_hook_name) == (
        hooked,
        None,
        "my_rule",
    )


async def test_replace_may_rewrite_the_opening_as_the_same_hook(client, db, with_author, fake_llm):
    version = await _start(
        client,
        fake_llm,
        _hook(
            "replace",
            replaced_text=DRAFT,
            replacing_text=(
                "Stop shipping big. Ship one small thing a week.\n\n"
                "every week i ship one tiny thing"
            ),
            replacing="stop_x_do_y",
            current="stop_x_do_y",
        ),
    )

    assert version["draft"] == (
        "Stop shipping big. Ship one small thing a week.\n\nevery week i ship one tiny thing"
    )
    attempt = await _stored_attempt(db)
    assert (attempt.current_hook_name, attempt.replacing_hook_name) == (
        "stop_x_do_y",
        "stop_x_do_y",
    )


FIRST_LINE = "shipping small beats shipping big"
ABOVE = f"Ship small.\n\n{FIRST_LINE}"


async def test_the_hook_calls_answer_is_stored_as_it_came(client, db, with_author, fake_llm):
    reply = _hook("replace", replaced_text=FIRST_LINE, replacing_text=ABOVE)
    await _start(client, fake_llm, dict(reply))

    assert (await _stored_attempt(db)).hook_answer == reply


async def test_a_refused_answer_is_stored_though_the_draft_goes_on_without_a_hook(
    client, db, with_author, fake_llm
):
    reply = _hook("replace", replaced_text="every week", replacing_text="Ship small.\nevery week")
    await _start(client, fake_llm, dict(reply))

    attempt = await _stored_attempt(db)
    assert (attempt.draft, attempt.replacing_hook_name, attempt.hook_answer) == (DRAFT, None, reply)


async def test_a_hook_call_that_raises_stores_no_answer(client, db, with_author, fake_llm):
    await _start(client, fake_llm, LLMError("provider down"))

    assert (await _stored_attempt(db)).hook_answer is None


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(LLMError("provider down"), id="the call raises"),
        pytest.param({"mode": "rewrite"}, id="the answer does not fit the schema"),
        pytest.param(
            _hook("prepend", replaced_text=FIRST_LINE, replacing_text=ABOVE),
            id="prepend is no mode",
        ),
        pytest.param(
            _hook("replace", replaced_text="every week", replacing_text="Ship small.\nevery week"),
            id="the replaced text is not a prefix",
        ),
        pytest.param(
            _hook("replace", replaced_text="", replacing_text="Ship small."),
            id="the replaced text is empty",
        ),
        pytest.param(
            _hook("replace", replaced_text=None, replacing_text="Ship small."),
            id="the replaced text is null",
        ),
        pytest.param(
            _hook(
                "replace",
                replaced_text="shipping small beats",
                replacing_text="Ship small.\nshipping small beats",
            ),
            id="the replaced text ends mid-line",
        ),
        pytest.param(
            _hook("replace", replaced_text=DRAFT, replacing_text="Ship small."),
            id="no line is carried",
        ),
        pytest.param(
            _hook(
                "replace",
                replaced_text=DRAFT,
                replacing_text="Ship small.\n\nEvery week I ship one tiny thing",
            ),
            id="the carried line is reworded",
        ),
        pytest.param(
            _hook("replace", replaced_text=FIRST_LINE, replacing_text=f"Ship small. {FIRST_LINE}"),
            id="the hook runs into the carried line",
        ),
        pytest.param(
            _hook("replace", replaced_text=FIRST_LINE, replacing_text=FIRST_LINE),
            id="no hook before the carried line",
        ),
        pytest.param(
            _hook("replace", replaced_text=FIRST_LINE, replacing_text=f"  \n\n{FIRST_LINE}"),
            id="a blank hook",
        ),
        pytest.param(
            _hook("replace", replaced_text=FIRST_LINE, replacing_text=f"\n{ABOVE}"),
            id="a blank line above the hook",
        ),
        pytest.param(
            _hook(
                "replace", replaced_text=FIRST_LINE, replacing_text=f"Ship small.\n\n\n{FIRST_LINE}"
            ),
            id="more than one blank line after the hook",
        ),
        pytest.param(
            _hook("replace", replaced_text=FIRST_LINE, replacing_text=None),
            id="the replacing text is null",
        ),
        pytest.param(
            _hook("replace", replaced_text=FIRST_LINE, replacing_text="a" * 3000 + ABOVE),
            id="the hooked draft is over the limit",
        ),
        pytest.param(
            _hook("replace", replaced_text=FIRST_LINE, replacing_text=ABOVE, replacing="made_up"),
            id="unknown replacing hook",
        ),
        pytest.param(
            _hook("keep", replacing=None, current="made_up"), id="unknown current hook on keep"
        ),
        pytest.param(
            _hook("replace", replaced_text=FIRST_LINE, replacing_text=ABOVE, current="made_up"),
            id="unknown current hook",
        ),
        pytest.param(
            _hook("replace", replaced_text=FIRST_LINE, replacing_text=ABOVE, replacing=None),
            id="no replacing hook",
        ),
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
    assert (
        attempt.current_hook_name,
        attempt.replacing_hook_name,
        attempt.hooking_model,
        attempt.hooking_usage,
    ) == (None, None, None, None)
    assert "Hook step failed" in caplog.text


async def test_a_hooked_draft_of_exactly_the_limit_is_kept(client, with_author, fake_llm):
    hook = "a" * (3000 - len(DRAFT) - 2)

    version = await _start(
        client,
        fake_llm,
        _hook("replace", replaced_text=FIRST_LINE, replacing_text=f"{hook}\n\n{FIRST_LINE}"),
    )

    assert version["draft"] == f"{hook}\n\n{DRAFT}"


async def test_a_feedback_version_jev_did_not_answer_makes_no_hook_call(
    client, db, with_author, fake_llm
):
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
    assert (feedback_version.replacing_hook_name, feedback_version.hooking_model) == (None, None)
    assert feedback_version.hooking_usage is None
