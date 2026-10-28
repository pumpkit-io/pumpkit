"""Starting a Post as a Thread, through the Posts API and the scripted model."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.posts.models import Post
from pumpkit.posts.writing.constants import THREAD_MAX_PARTS
from pumpkit.posts.writing.prompts.humanizer_thread import humanizer_thread_prompt
from pumpkit.posts.writing.prompts.sketch_post import sketch_post_prompt
from pumpkit.posts.writing.prompts.sketch_thread import sketch_thread_prompt
from pumpkit.x_connection.x_length import X_POST_MAX_CHARS
from tests.posts.writing_replies import written, written_thread

AUTHORS = "/api/v1/inspiration-authors"
POSTS = "/api/v1/posts"


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


async def _stored_attempts(db):
    result = await db.execute(select(Post).options(selectinload(Post.attempts)))
    [post] = result.scalars()
    return post.attempts


async def test_starting_a_post_as_a_thread_returns_a_first_version_of_parts(
    client, db, with_author, fake_llm
):
    fake_llm.replies = [
        written_thread(["Ship small—every week", "it’s how you learn"]),
        {
            "parts": [
                "Ship small every week 🚀",
                "it's how you learn https://pumpkit.io/a/long/link",
            ]
        },
    ]

    response = await client.post(POSTS, json={"brief": "ship small things", "format": "thread"})

    assert response.status_code == 201, response.text
    [version] = response.json()["versions"]
    assert version["format"] == "thread"
    assert version["parts"] == [
        {"text": "Ship small every week 🚀", "char_count": 24, "char_limit": 280},
        {
            "text": "it's how you learn https://pumpkit.io/a/long/link",
            "char_count": 42,
            "char_limit": 280,
        },
    ]
    [attempt] = await _stored_attempts(db)
    assert (attempt.format, attempt.sketch_parts, attempt.parts) == (
        "thread",
        ["Ship small - every week", "it's how you learn"],
        ["Ship small every week 🚀", "it's how you learn https://pumpkit.io/a/long/link"],
    )


def _system(prompt: str) -> dict:
    block = {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    return {"role": "system", "content": [block]}


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


LEVELSIO_CORPUS = (
    "Below are real posts by the writers whose voice you are reproducing, grouped by author. "
    "They are examples of HOW to write, never of what to write about.\n\n"
    '<creator handle="levelsio">\n'
    "<post>levelsio post 0</post>\n"
    "</creator>"
)


async def test_a_thread_is_sketched_and_humanized_with_the_thread_prompts_and_schemas(
    client, with_author, fake_llm
):
    fake_llm.replies = [
        written_thread(["part one—here", "part two"]),
        {"parts": ["final one", "final two"]},
    ]

    await client.post(POSTS, json={"brief": "ship small things", "format": "thread"})

    sketch_call, humanizer_call = fake_llm.calls
    assert sketch_call.response_model.__name__ == "drafted_thread"
    assert sketch_call.messages == [
        _system(sketch_thread_prompt(X_POST_MAX_CHARS)),
        _user(LEVELSIO_CORPUS),
        _user("ship small things"),
    ]
    assert humanizer_call.response_model.__name__ == "refined_thread"
    assert humanizer_call.messages == [
        _system(humanizer_thread_prompt(X_POST_MAX_CHARS)),
        _user(LEVELSIO_CORPUS),
        _user(
            "This is the brief the thread below was written from. Use it only to keep the "
            "rewrite true to what it asks for - its position and any explicit asks. Do not "
            "add anything from it that the thread does not already say.\n\n"
            "<brief>\nship small things\n</brief>"
        ),
        _user(
            '<part number="1">\npart one - here\n</part>\n\n<part number="2">\npart two\n</part>'
        ),
    ]


async def test_a_thread_of_the_most_parts_allowed_is_kept_whole(client, with_author, fake_llm):
    parts = [f"part {n}" for n in range(1, THREAD_MAX_PARTS + 1)]
    fake_llm.replies = [written_thread(parts), {"parts": parts}]

    response = await client.post(POSTS, json={"brief": "ship", "format": "thread"})

    assert response.status_code == 201
    assert [part["text"] for part in response.json()["versions"][0]["parts"]] == parts


TOO_MANY = [f"part {n}" for n in range(1, THREAD_MAX_PARTS + 2)]


@pytest.mark.parametrize(
    "replies",
    [
        pytest.param([written_thread(["just one"])], id="sketch of one Part"),
        pytest.param([written_thread(TOO_MANY)], id="sketch over the cap"),
        pytest.param([written_thread(["one", "  "])], id="sketch with a blank Part"),
        pytest.param([written_thread(["one", "two"]), {"parts": ["one"]}], id="final of one Part"),
        pytest.param([written_thread(["one", "two"]), {"parts": TOO_MANY}], id="final over cap"),
    ],
)
async def test_a_thread_reply_outside_the_part_bounds_fails_the_attempt(
    client, db, with_author, fake_llm, assert_reported_502, replies
):
    fake_llm.replies = replies

    response = await client.post(POSTS, json={"brief": "ship", "format": "thread"})

    assert_reported_502(response)
    assert fake_llm.replies == []
    [attempt] = await _stored_attempts(db)
    assert (attempt.status, attempt.format, attempt.parts) == ("failed", "thread", None)


async def test_a_post_started_with_the_post_format_is_a_single_post(client, with_author, fake_llm):
    fake_llm.replies = [written("sketch"), {"post": "final"}]

    response = await client.post(POSTS, json={"brief": "ship", "format": "post"})

    [version] = response.json()["versions"]
    assert (version["format"], len(version["parts"])) == ("post", 1)
    assert fake_llm.calls[0].messages[0] == _system(sketch_post_prompt(X_POST_MAX_CHARS))


async def test_an_unknown_format_returns_422(client, with_author, fake_llm):
    response = await client.post(POSTS, json={"brief": "ship", "format": "carousel"})

    assert response.status_code == 422
    assert fake_llm.calls == []
