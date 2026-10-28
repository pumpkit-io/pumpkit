"""Writing a Version for the post limit of the User's X account, in either Format."""

from datetime import datetime, timedelta, timezone

import pytest

import pumpkit.posts.mediator as posts_mediator
import pumpkit.x_connection.service as x_connections_service
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.posts.writing.prompts.humanizer import HUMANIZER_PROMPT
from pumpkit.posts.writing.prompts.humanizer_thread import humanizer_thread_prompt
from pumpkit.posts.writing.prompts.sketch_post import sketch_post_prompt
from pumpkit.posts.writing.prompts.sketch_thread import sketch_thread_prompt
from pumpkit.x_connection.x_length import X_LONG_POST_MAX_CHARS, X_POST_MAX_CHARS
from pumpkit.x_connection.x_publisher import XAccount
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


@pytest.fixture
def connect_x_as(fake_x_publisher, clock, connect_x):
    async def _connect(subscription_type: str) -> None:
        fake_x_publisher.account = XAccount(
            user_id="1001", handle="ada", subscription_type=subscription_type
        )
        await connect_x()

    return _connect


def _system_text(call) -> str:
    return call.messages[0]["content"][0]["text"]


def _limits(version: dict) -> list[int]:
    return [part["char_limit"] for part in version["parts"]]


async def test_without_an_x_connection_both_formats_are_written_for_xs_default_limit(
    client, with_author, fake_llm
):
    fake_llm.replies = [
        written("sketch"),
        {"post": "final"},
        written_thread(["one", "two"]),
        {"parts": ["one", "two"]},
    ]

    post = await client.post(POSTS, json={"brief": "ship"})
    thread = await client.post(POSTS, json={"brief": "ship", "format": "thread"})

    assert _limits(post.json()["versions"][0]) == [X_POST_MAX_CHARS]
    assert _limits(thread.json()["versions"][0]) == [X_POST_MAX_CHARS, X_POST_MAX_CHARS]
    assert [_system_text(call) for call in fake_llm.calls] == [
        sketch_post_prompt(X_POST_MAX_CHARS),
        HUMANIZER_PROMPT,
        sketch_thread_prompt(X_POST_MAX_CHARS),
        humanizer_thread_prompt(X_POST_MAX_CHARS),
    ]


@pytest.mark.parametrize(
    ("subscription_type", "char_limit"),
    [
        ("None", X_POST_MAX_CHARS),
        ("Basic", X_POST_MAX_CHARS),
        ("Premium", X_LONG_POST_MAX_CHARS),
        ("PremiumPlus", X_LONG_POST_MAX_CHARS),
    ],
)
async def test_a_thread_is_written_for_the_x_accounts_limit_like_a_single_post(
    client, with_author, fake_llm, connect_x_as, subscription_type, char_limit
):
    await connect_x_as(subscription_type)
    fake_llm.replies = [
        written("sketch"),
        {"post": "final"},
        written_thread(["one", "two"]),
        {"parts": ["one", "two"]},
    ]

    post = await client.post(POSTS, json={"brief": "ship"})
    thread = await client.post(POSTS, json={"brief": "ship", "format": "thread"})

    assert _limits(post.json()["versions"][0]) == [char_limit]
    assert _limits(thread.json()["versions"][0]) == [char_limit, char_limit]
    assert [_system_text(call) for call in fake_llm.calls] == [
        sketch_post_prompt(char_limit),
        HUMANIZER_PROMPT,
        sketch_thread_prompt(char_limit),
        humanizer_thread_prompt(char_limit),
    ]


async def test_feedback_after_buying_x_premium_writes_and_shows_the_longer_limit(
    client, db, user, with_author, fake_llm, connect_x_as
):
    await connect_x_as("None")
    fake_llm.replies = [written_thread(["one", "two"]), {"parts": ["one", "two"]}]
    post_id = (await client.post(POSTS, json={"brief": "ship", "format": "thread"})).json()["id"]
    connection = await x_connections_service.get_connection(db, user_id=user.id)
    assert connection is not None
    await x_connections_service.save_subscription_type(
        db, connection, subscription_type="Premium", now=datetime.now(timezone.utc)
    )
    await db.commit()
    fake_llm.replies = [written_thread(["one", "two"]), {"parts": ["one", "two"]}]

    response = await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "longer"})

    assert _limits(response.json()) == [X_LONG_POST_MAX_CHARS, X_LONG_POST_MAX_CHARS]
    assert _system_text(fake_llm.calls[2]) == sketch_thread_prompt(X_LONG_POST_MAX_CHARS)
    assert _system_text(fake_llm.calls[3]) == humanizer_thread_prompt(X_LONG_POST_MAX_CHARS)
    read = await posts_mediator.get_post(db, user, post_id)
    assert [[part.char_limit for part in v.parts] for v in read.versions] == [
        [X_LONG_POST_MAX_CHARS] * 2
    ] * 2
