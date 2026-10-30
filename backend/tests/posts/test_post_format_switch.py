"""Switching or keeping a Post's Format with Feedback, through the Posts API."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.posts.llm import LLMError
from pumpkit.posts.models import Post
from pumpkit.posts.writing.prompts.humanizer import HUMANIZER_PROMPT
from pumpkit.posts.writing.prompts.humanizer_thread import humanizer_thread_prompt
from pumpkit.posts.writing.prompts.sketch_post import sketch_post_prompt
from pumpkit.posts.writing.prompts.sketch_thread import sketch_thread_prompt
from pumpkit.x_connection.x_length import X_POST_MAX_CHARS
from tests.posts.writing_replies import written, written_thread

AUTHORS = "/api/v1/inspiration-authors"
POSTS = "/api/v1/posts"


def _versions_url(post_id: str) -> str:
    return f"{POSTS}/{post_id}/versions"


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


async def _start(client, fake_llm, format: str) -> str:
    """A Post whose first version's text is "final 1", or the Thread "final a", "final b"."""
    if format == "thread":
        fake_llm.replies = [
            written_thread(["sketch a", "sketch b"]),
            {"parts": ["final a", "final b"]},
        ]
    else:
        fake_llm.replies = [written("sketch 1"), {"post": "final 1"}]
    response = await client.post(POSTS, json={"brief": "ship small things", "format": format})
    assert response.status_code == 201, response.text
    fake_llm.calls.clear()
    return response.json()["id"]


async def _feedback(client, post_id: str, feedback: str, format: str | None = None):
    body = {"feedback": feedback} if format is None else {"feedback": feedback, "format": format}
    return await client.post(_versions_url(post_id), json=body)


async def test_feedback_with_the_thread_format_turns_a_single_post_into_a_thread(
    client, with_author, fake_llm
):
    post_id = await _start(client, fake_llm, "post")
    fake_llm.replies = [written_thread(["one", "two"]), {"parts": ["final one", "final two"]}]

    response = await _feedback(client, post_id, "expand it", "thread")

    assert response.status_code == 201, response.text
    version = response.json()
    assert version["format"] == "thread"
    assert [part["text"] for part in version["parts"]] == ["final one", "final two"]
    assert [part["char_limit"] for part in version["parts"]] == [280, 280]
    assert [call.response_model.__name__ for call in fake_llm.calls] == [
        "revised_thread",
        "refined_thread",
    ]


async def test_feedback_with_the_post_format_turns_a_thread_into_a_single_post(
    client, with_author, fake_llm
):
    post_id = await _start(client, fake_llm, "thread")
    fake_llm.replies = [written("one post"), {"post": "final post"}]

    response = await _feedback(client, post_id, "condense it", "post")

    version = response.json()
    assert (version["format"], version["parts"]) == (
        "post",
        [{"text": "final post", "char_count": 10, "char_limit": X_POST_MAX_CHARS}],
    )
    assert [call.response_model.__name__ for call in fake_llm.calls] == [
        "revised_post",
        "refined_post",
    ]


@pytest.mark.parametrize(
    ("format", "replies"),
    [
        ("post", [written("sketch 2"), {"post": "final 2"}]),
        ("thread", [written_thread(["c", "d"]), {"parts": ["final c", "final d"]}]),
    ],
)
async def test_feedback_without_a_format_keeps_the_latest_versions_format(
    client, with_author, fake_llm, format, replies
):
    post_id = await _start(client, fake_llm, format)
    fake_llm.replies = replies

    response = await _feedback(client, post_id, "warmer")

    assert response.json()["format"] == format


async def test_feedback_without_a_format_keeps_the_format_of_a_switched_version(
    client, with_author, fake_llm
):
    post_id = await _start(client, fake_llm, "post")
    fake_llm.replies = [written_thread(["a", "b"]), {"parts": ["a", "b"]}]
    await _feedback(client, post_id, "expand it", "thread")
    fake_llm.replies = [written_thread(["c", "d"]), {"parts": ["c", "d"]}]

    response = await _feedback(client, post_id, "warmer")

    assert response.json()["format"] == "thread"


async def test_a_failed_switch_records_the_format_it_was_asked_for(
    client, db, with_author, fake_llm, assert_reported_502
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


async def test_a_revised_thread_outside_the_part_bounds_fails_the_attempt(
    client, with_author, fake_llm, assert_reported_502
):
    post_id = await _start(client, fake_llm, "thread")
    fake_llm.replies = [written_thread(["just one"])]

    response = await _feedback(client, post_id, "shorter")

    assert_reported_502(response)


def _system(prompt: str) -> dict:
    block = {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    return {"role": "system", "content": [block]}


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


def _assistant(content: str) -> dict:
    return {"role": "assistant", "content": content}


LEVELSIO_CORPUS = (
    "Below are real posts by the writers whose voice you are reproducing, grouped by author. "
    "They are examples of HOW to write, never of what to write about.\n\n"
    '<creator handle="levelsio">\n'
    "<post>levelsio post 0</post>\n"
    "</creator>"
)

THREAD_FINAL = '<part number="1">\nfinal a\n</part>\n\n<part number="2">\nfinal b\n</part>'


async def _mixed_history(client, fake_llm) -> str:
    """A single post, then a Thread from "expand it", then the Thread revised by "warmer Part 2"."""
    post_id = await _start(client, fake_llm, "post")
    fake_llm.replies = [written_thread(["a", "b"]), {"parts": ["final a", "final b"]}]
    await _feedback(client, post_id, "expand it", "thread")
    fake_llm.replies = [written_thread(["a", "b2"]), {"parts": ["final a", "final b2"]}]
    await _feedback(client, post_id, "warmer Part 2")
    fake_llm.calls.clear()
    return post_id


async def test_the_revision_call_renders_each_final_in_its_own_format_and_states_the_new_one(
    client, with_author, fake_llm
):
    post_id = await _mixed_history(client, fake_llm)
    fake_llm.replies = [written("one post"), {"post": "final post"}]

    await _feedback(client, post_id, "condense it", "post")

    revision_call = fake_llm.calls[0]
    assert revision_call.messages == [
        _system(sketch_post_prompt(X_POST_MAX_CHARS)),
        _user(LEVELSIO_CORPUS),
        _user("ship small things"),
        _assistant("final 1"),
        _user(
            "That was Version 1.\n\n"
            "Rewrite the post you just wrote as a thread, according to this feedback. Keep "
            "what it says and how it says it wherever the feedback does not ask for a change, "
            "spread over the parts the thread needs, and return the whole thread.\n\n"
            "The feedback:\nexpand it"
        ),
        _assistant(THREAD_FINAL),
        _user(
            "That was Version 2.\n\n"
            "Change the thread you just wrote according to this feedback, and change nothing "
            "else. Keep every part the feedback does not ask about exactly as it is, and return "
            "the whole thread rather than only the part that changed.\n\n"
            "The feedback:\nwarmer Part 2"
        ),
        _assistant('<part number="1">\nfinal a\n</part>\n\n<part number="2">\nfinal b2\n</part>'),
        _user(
            "That was Version 3.\n\n"
            "Rewrite the thread you just wrote as a single post, according to this feedback. "
            "Keep what it says and how it says it wherever the feedback does not ask for a "
            "change and one post has room for it, and return the whole post.\n\n"
            "The feedback:\ncondense it"
        ),
    ]


async def test_a_revision_that_keeps_a_thread_is_written_under_the_thread_prompt(
    client, with_author, fake_llm
):
    post_id = await _start(client, fake_llm, "thread")
    fake_llm.replies = [written_thread(["c", "d"]), {"parts": ["c", "d"]}]

    await _feedback(client, post_id, "warmer")

    assert fake_llm.calls[0].messages[0] == _system(sketch_thread_prompt(X_POST_MAX_CHARS))
    assert fake_llm.calls[0].messages[3] == _assistant(THREAD_FINAL)


async def test_the_revision_humanizer_gets_the_previous_thread_as_parts_and_the_new_post(
    client, with_author, fake_llm
):
    post_id = await _start(client, fake_llm, "thread")
    fake_llm.replies = [written("one—post"), {"post": "final post"}]

    await _feedback(client, post_id, "condense it", "post")

    assert fake_llm.calls[1].messages[0] == _system(HUMANIZER_PROMPT)
    assert fake_llm.calls[1].messages[3:] == [
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


async def test_the_revision_humanizer_gets_the_previous_post_and_the_new_thread_as_parts(
    client, with_author, fake_llm
):
    post_id = await _start(client, fake_llm, "post")
    fake_llm.replies = [written_thread(["one", "two"]), {"parts": ["final one", "final two"]}]

    await _feedback(client, post_id, "expand it", "thread")

    humanizer_call = fake_llm.calls[1]
    assert humanizer_call.messages[0] == _system(humanizer_thread_prompt(X_POST_MAX_CHARS))
    assert humanizer_call.messages[3:] == [
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
    client, with_author, fake_llm
):
    post_id = await _start(client, fake_llm, "thread")
    fake_llm.replies = [written("one post"), {"post": "final post"}]
    await _feedback(client, post_id, "condense it", "post")
    await client.post(f"{POSTS}/{post_id}/versions/1/restore")
    fake_llm.replies = [written_thread(["c", "d"]), {"parts": ["final c", "final d"]}]
    fake_llm.calls.clear()

    response = await _feedback(client, post_id, "warmer")

    assert response.json()["format"] == "thread"
    assert fake_llm.calls[0].messages[0] == _system(sketch_thread_prompt(X_POST_MAX_CHARS))
    assert fake_llm.calls[0].messages[-1] == _user(
        "That was Version 2. I went back to Version 1.\n\n"
        "Change Version 1 according to this feedback, and change nothing else. Keep every part "
        "the feedback does not ask about exactly as it is, and return the whole thread rather "
        "than only the part that changed.\n\nThe feedback:\nwarmer"
    )
    assert fake_llm.calls[1].messages[4] == _user(
        "This is the thread as I last saw it, before my latest feedback.\n\n"
        f"<previous_thread>\n{THREAD_FINAL}\n</previous_thread>"
    )


async def test_an_unknown_feedback_format_returns_422(client, with_author, fake_llm):
    post_id = await _start(client, fake_llm, "post")

    response = await _feedback(client, post_id, "expand it", "carousel")

    assert response.status_code == 422
    assert fake_llm.calls == []
