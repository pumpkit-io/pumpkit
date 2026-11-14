"""
Switching or keeping a Post's Format with Feedback, through the Posts API: the revise call and the
revision humanizer run under the prompts of the Format the Feedback asks for, with Pumpkit's switch
framing (ADR 0016, ADR 0026).
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pumpkit.core.llm import LLMCall, LLMError
from pumpkit.posts.models import Post
from pumpkit.x_connection.x_length import X_LONG_POST_MAX_CHARS, X_POST_MAX_CHARS
from pumpkit.x_connection.x_publisher import XAccount
from tests.positioning.positioning import TEXT, save_positioning
from tests.posts.writing_replies import (
    HUMANIZED_POST,
    HUMANIZED_THREAD,
    REVISED_POST,
    REVISED_THREAD,
    revised,
    revised_thread,
    start_thread,
)

POSTS = "/api/v1/posts"
CACHED = {"type": "ephemeral", "ttl": "1h"}


def _inputs(core_idea: str, choices: str) -> str:
    return (
        "<raw_input>\nship small things\n</raw_input>\n\n"
        f"<positioning>\n{TEXT}\n</positioning>\n\n"
        f"<core_idea>\n{core_idea}\n</core_idea>\n\n"
        "<takeaway>\nShip the smallest thing that works this week.\n</takeaway>\n\n"
        f"<choices>\nfunnel: MOF\ndesired_action: bookmark\n{choices}</choices>"
    )


# The default single post's Plan as a Thread: few_lines is a post's structure only, so it goes.
POST_AS_THREAD = _inputs("Shipping small things beats planning big ones.", "format: thread\n")
# The default Thread's Plan as a post on a 280-character account.
THREAD_AS_POST = _inputs(
    "Five lessons from shipping small things every week.",
    "format: short\nstructure: hook_list_closer\n",
)
THREAD_FINAL = '<part number="1">\nfinal a\n</part>\n\n<part number="2">\nfinal b\n</part>'


@pytest.fixture
async def ready(client, subscribed):
    """A User with a Positioning and no Inspiration authors."""
    await save_positioning(client)


async def _start(client, fake_llm, format: str) -> str:
    """A Post whose first version's text is "final 1", or the Thread "final a", "final b"."""
    if format == "thread":
        response = await start_thread(client, fake_llm, ["final a", "final b"])
    else:
        fake_llm.replies = [{"post": "final 1"}]
        response = await client.post(POSTS, json={"brief": "ship small things"})
    assert response.status_code == 201, response.text
    fake_llm.calls.clear()
    return response.json()["id"]


async def _feedback(client, post_id: str, feedback: str, format: str | None = None):
    body = {"feedback": feedback} if format is None else {"feedback": feedback, "format": format}
    return await client.post(f"{POSTS}/{post_id}/versions", json=body)


def _calls(fake_llm, schema: type) -> list[LLMCall]:
    return [call for call in fake_llm.calls if call.response_model is schema]


def _system_text(call: LLMCall) -> str:
    [block] = call.messages[0]["content"]
    assert block["cache_control"] == CACHED
    return block["text"]


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


def _assistant(content: str) -> dict:
    return {"role": "assistant", "content": content}


TO_A_THREAD = (
    "That was Version 1.\n\n"
    "Rewrite the post you just wrote as a thread, according to this feedback. Keep "
    "what it says and how it says it wherever the feedback does not ask for a change, "
    "spread over the parts the thread needs, and return the whole thread.\n\n"
    "The feedback:\nexpand it"
)


def _to_a_post(version: int) -> str:
    return (
        f"That was Version {version}.\n\n"
        "Rewrite the thread you just wrote as a single post, according to this feedback. "
        "Keep what it says and how it says it wherever the feedback does not ask for a "
        "change and one post has room for it, and return the whole post.\n\n"
        "The feedback:\ncondense it"
    )


async def test_feedback_with_the_thread_format_turns_a_single_post_into_a_thread(
    client, ready, fake_llm
):
    post_id = await _start(client, fake_llm, "post")
    fake_llm.replies = [{"parts": ["final one", "final two"]}]

    response = await _feedback(client, post_id, "expand it", "thread")

    assert response.status_code == 201, response.text
    version = response.json()
    assert version["format"] == "thread"
    assert [part["text"] for part in version["parts"]] == ["final one", "final two"]
    assert [part["char_limit"] for part in version["parts"]] == [280, 280]
    assert [call.response_model for call in fake_llm.calls] == [REVISED_THREAD, HUMANIZED_THREAD]
    assert [call.response_model.__name__ for call in fake_llm.calls] == [
        "revised_thread",
        "refined_thread",
    ]


async def test_feedback_with_the_post_format_turns_a_thread_into_a_single_post(
    client, ready, fake_llm
):
    post_id = await _start(client, fake_llm, "thread")
    fake_llm.replies = [{"post": "final post"}]

    response = await _feedback(client, post_id, "condense it", "post")

    version = response.json()
    assert (version["format"], version["parts"]) == (
        "post",
        [{"text": "final post", "char_count": 10, "char_limit": X_POST_MAX_CHARS}],
    )
    assert [call.response_model for call in fake_llm.calls] == [REVISED_POST, HUMANIZED_POST]


@pytest.mark.parametrize(
    ("format", "replies"),
    [("post", [{"post": "final 2"}]), ("thread", [{"parts": ["final c", "final d"]}])],
)
async def test_feedback_without_a_format_keeps_the_latest_versions_format(
    client, ready, fake_llm, format, replies
):
    post_id = await _start(client, fake_llm, format)
    fake_llm.replies = replies

    response = await _feedback(client, post_id, "warmer")

    assert response.json()["format"] == format


async def test_feedback_without_a_format_keeps_the_format_of_a_switched_version(
    client, ready, fake_llm
):
    post_id = await _start(client, fake_llm, "post")
    fake_llm.replies = [{"parts": ["a", "b"]}, {"parts": ["c", "d"]}]
    await _feedback(client, post_id, "expand it", "thread")

    response = await _feedback(client, post_id, "warmer")

    assert response.json()["format"] == "thread"
    assert [call.response_model for call in fake_llm.calls][-2:] == [
        REVISED_THREAD,
        HUMANIZED_THREAD,
    ]


async def test_a_failed_switch_records_the_format_it_was_asked_for(
    client, db, ready, fake_llm, assert_reported_502
):
    post_id = await _start(client, fake_llm, "post")
    fake_llm.replies = [LLMError("provider down")]

    response = await _feedback(client, post_id, "expand it", "thread")

    assert_reported_502(response)
    result = await db.execute(select(Post).options(selectinload(Post.attempts)))
    [post] = result.scalars()
    assert [(a.status, a.format) for a in post.attempts] == [
        ("succeeded", "post"),
        ("failed", "thread"),
    ]


@pytest.mark.parametrize(
    "parts",
    [["just one"], [f"part {n}" for n in range(1, 12)], ["one", "  "]],
    ids=["one Part", "eleven Parts", "a blank Part"],
)
async def test_a_revised_thread_outside_the_part_bounds_fails_the_attempt(
    client, ready, fake_llm, assert_reported_502, parts
):
    post_id = await _start(client, fake_llm, "thread")
    fake_llm.standing[REVISED_THREAD] = revised_thread(parts)

    response = await _feedback(client, post_id, "shorter")

    assert_reported_502(response)
    assert _calls(fake_llm, HUMANIZED_THREAD) == []


async def test_a_switch_to_a_thread_runs_under_the_thread_revise_prompt_without_a_posts_structure(
    client, ready, fake_llm
):
    post_id = await _start(client, fake_llm, "post")
    fake_llm.replies = [{"parts": ["a", "b"]}]

    await _feedback(client, post_id, "expand it", "thread")

    [revise] = _calls(fake_llm, REVISED_THREAD)
    prompt = _system_text(revise)
    assert prompt.startswith("# Role\n\nYou revise one thread on X written on my behalf")
    assert "# Format: thread" in prompt
    assert "# The structure across the parts" in prompt
    assert "# Structure:" not in prompt
    assert "few_lines" not in prompt
    assert "one-line structure" not in prompt
    assert revise.messages[1:] == [
        _user(POST_AS_THREAD),
        _assistant("final 1"),
        _user(TO_A_THREAD),
    ]


async def test_a_switch_to_a_post_runs_under_the_post_revise_prompt_with_the_accounts_length(
    client, ready, fake_llm
):
    post_id = await _start(client, fake_llm, "thread")
    fake_llm.replies = [{"post": "final post"}]

    await _feedback(client, post_id, "condense it", "post")

    [revise] = _calls(fake_llm, REVISED_POST)
    prompt = _system_text(revise)
    assert prompt.startswith("# Role\n\nYou revise one post on X written on my behalf")
    assert "# Format: short post\n\n- At most 280 characters as X counts them" in prompt
    assert "# Structure: hook, list, closer" in prompt
    assert "# Format: thread" not in prompt
    assert revise.messages[1:] == [
        _user(THREAD_AS_POST),
        _assistant(THREAD_FINAL),
        _user(_to_a_post(1)),
    ]


async def test_a_thread_switched_to_a_post_on_a_premium_account_is_a_long_post(
    client, ready, fake_llm, fake_x_publisher, connect_x
):
    fake_x_publisher.account = XAccount(user_id="1001", handle="ada", subscription_type="Premium")
    await connect_x()
    post_id = await _start(client, fake_llm, "thread")
    fake_llm.replies = [{"post": "final post"}]

    response = await _feedback(client, post_id, "condense it", "post")

    assert response.json()["parts"][0]["char_limit"] == X_LONG_POST_MAX_CHARS
    [revise] = _calls(fake_llm, REVISED_POST)
    prompt = _system_text(revise)
    assert "# Format: long post" in prompt
    assert "Hard limit: 25,000 characters." in prompt
    assert "format: long\nstructure: hook_list_closer\n" in revise.messages[1]["content"]
    [humanizer] = _calls(fake_llm, HUMANIZED_POST)
    assert "at most 25,000 characters" in _system_text(humanizer)


async def _mixed_history(client, fake_llm) -> str:
    """A single post, then a Thread from "expand it", then the Thread revised by "warmer Part 2"."""
    post_id = await _start(client, fake_llm, "post")
    fake_llm.replies = [{"parts": ["final a", "final b"]}, {"parts": ["final a", "final b2"]}]
    await _feedback(client, post_id, "expand it", "thread")
    await _feedback(client, post_id, "warmer Part 2")
    fake_llm.calls.clear()
    return post_id


async def test_the_revise_call_renders_each_version_in_its_own_format_and_states_the_switch(
    client, ready, fake_llm
):
    post_id = await _mixed_history(client, fake_llm)
    fake_llm.replies = [{"post": "final post"}]

    await _feedback(client, post_id, "condense it", "post")

    [revise] = _calls(fake_llm, REVISED_POST)
    assert revise.messages[2:] == [
        _assistant("final 1"),
        _user(TO_A_THREAD),
        _assistant(THREAD_FINAL),
        _user(
            "That was Version 2.\n\n"
            "Change the thread you just wrote according to this feedback, and change nothing "
            "else. Keep every part the feedback does not ask about exactly as it is, and return "
            "the whole thread rather than only the part that changed.\n\n"
            "The feedback:\nwarmer Part 2"
        ),
        _assistant('<part number="1">\nfinal a\n</part>\n\n<part number="2">\nfinal b2\n</part>'),
        _user(_to_a_post(3)),
    ]


async def test_the_post_revision_humanizer_gets_the_previous_thread_as_parts_and_the_new_post(
    client, ready, fake_llm
):
    post_id = await _start(client, fake_llm, "thread")
    fake_llm.standing[REVISED_POST] = revised("one—post")
    fake_llm.replies = [{"post": "final post"}]

    await _feedback(client, post_id, "condense it", "post")

    [humanizer] = _calls(fake_llm, HUMANIZED_POST)
    assert _system_text(humanizer).startswith(
        "# Role\n\nYou rewrite one post on X on my behalf to make it sound human"
    )
    assert "format: short\nstructure: hook_list_closer\n" in humanizer.messages[1]["content"]
    assert humanizer.messages[2:] == [
        _user(
            "This is the thread as I last saw it, before my latest feedback.\n\n"
            f"<previous_thread>\n{THREAD_FINAL}\n</previous_thread>"
        ),
        _user(
            "This is my latest feedback on that thread. The post below already applies it, "
            "including turning the thread into a post, so don't apply it again, and "
            "don't add, remove or reorder anything to serve it. If it asks for something your "
            "guidelines would undo, keep what it asks for.\n\n"
            "<feedback>\ncondense it\n</feedback>"
        ),
        _user(
            "This is the post to rewrite. Return every sentence that is also in the previous "
            "thread exactly as it is in <post> below, even if it moved. A sentence that differs "
            "only in punctuation counts as unchanged. Apply your guidelines only to the "
            "sentences that are new or reworded, and don't add sentences or ideas the post "
            "doesn't have.\n\n"
            "<post>\none - post\n</post>"
        ),
    ]


async def test_the_thread_revision_humanizer_gets_the_previous_post_and_the_new_thread_as_parts(
    client, ready, fake_llm
):
    post_id = await _start(client, fake_llm, "post")
    fake_llm.standing[REVISED_THREAD] = revised_thread(["one", "two"])
    fake_llm.replies = [{"parts": ["final one", "final two"]}]

    await _feedback(client, post_id, "expand it", "thread")

    [humanizer] = _calls(fake_llm, HUMANIZED_THREAD)
    system = _system_text(humanizer)
    assert system.startswith("# Role\n\nYou rewrite one thread on X on my behalf")
    assert "- The structure: keep the order of the parts, one point per part" in system
    assert "few_lines" not in system
    assert "format: thread\n</plan>" in humanizer.messages[1]["content"]
    assert humanizer.messages[2:] == [
        _user(
            "This is the post as I last saw it, before my latest feedback.\n\n"
            "<previous_post>\nfinal 1\n</previous_post>"
        ),
        _user(
            "This is my latest feedback on that post. The thread below already applies it, "
            "including turning the post into a thread, so don't apply it again, and don't add, "
            "remove or reorder anything to serve it. If it asks for something your guidelines "
            "would undo, keep what it asks for.\n\n"
            "<feedback>\nexpand it\n</feedback>"
        ),
        _user(
            "This is the thread to rewrite. Return every sentence that is also in the previous "
            "post exactly as it is in <thread> below, even if it moved. A sentence that differs "
            "only in punctuation counts as unchanged. Apply your guidelines only to the "
            "sentences that are new or reworded, and don't add sentences or ideas the thread "
            "doesn't have.\n\n"
            '<thread>\n<part number="1">\none\n</part>\n\n<part number="2">\ntwo\n</part>\n'
            "</thread>"
        ),
    ]


async def test_feedback_after_restoring_a_thread_keeps_the_texts_format_and_says_so(
    client, ready, fake_llm
):
    post_id = await _start(client, fake_llm, "thread")
    fake_llm.replies = [{"post": "final post"}]
    await _feedback(client, post_id, "condense it", "post")
    await client.post(f"{POSTS}/{post_id}/versions/1/restore")
    fake_llm.replies = [{"parts": ["final c", "final d"]}]
    fake_llm.calls.clear()

    response = await _feedback(client, post_id, "warmer")

    assert response.json()["format"] == "thread"
    revise, humanizer = fake_llm.calls
    assert _system_text(revise).startswith("# Role\n\nYou revise one thread on X")
    assert revise.messages[-1] == _user(
        "That was Version 2. I went back to Version 1.\n\n"
        "Change Version 1 according to this feedback, and change nothing else. Keep every part "
        "the feedback does not ask about exactly as it is, and return the whole thread rather "
        "than only the part that changed.\n\nThe feedback:\nwarmer"
    )
    assert humanizer.messages[3] == _user(
        "This is the thread as I last saw it, before my latest feedback.\n\n"
        f"<previous_thread>\n{THREAD_FINAL}\n</previous_thread>"
    )


async def test_an_unknown_feedback_format_returns_422(client, ready, fake_llm):
    post_id = await _start(client, fake_llm, "post")

    response = await _feedback(client, post_id, "expand it", "carousel")

    assert response.status_code == 422
    assert fake_llm.calls == []
