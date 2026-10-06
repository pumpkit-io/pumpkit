from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.datetimes import as_utc
from app.core.llm import LLMError
from app.core.x_reader import FetchedPost
from app.db.models import Post, User
from app.writing.constants import HUMANIZING_MODEL, REVISING_MODEL
from app.writing.prompts.draft_post import DRAFT_POST_PROMPT
from app.writing.prompts.humanizer import HUMANIZER_PROMPT

AUTHORS = "/api/v1/inspiration-authors"
POSTS = "/api/v1/posts"


def _versions_url(post_id: str) -> str:
    return f"{POSTS}/{post_id}/versions"


def _posts(handle: str, count: int) -> list[FetchedPost]:
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return [
        FetchedPost(
            post_id=f"{handle}-{n}", text=f"{handle} post {n}", posted_at=start - timedelta(hours=n)
        )
        for n in range(count)
    ]


@pytest.fixture
async def post_id(client, subscribed, fake_x_reader, fake_llm) -> str:
    """A Post from the Brief "ship small things" whose first Version's Final is "final 1"."""
    fake_x_reader.posts["levelsio"] = _posts("levelsio", 2)
    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201
    fake_llm.replies = [{"post": "draft 1"}, {"post": "final 1"}]
    response = await client.post(POSTS, json={"brief": "ship small things"})
    assert response.status_code == 201
    fake_llm.calls.clear()
    return response.json()["id"]


async def test_feedback_returns_a_new_version_with_the_next_number(client, post_id, fake_llm):
    fake_llm.replies = [{"post": "draft 2—shorter"}, {"post": "final 2"}]

    response = await client.post(_versions_url(post_id), json={"feedback": "make it shorter"})

    assert response.status_code == 201
    version = response.json()
    assert version["number"] == 2
    assert version["feedback"] == "make it shorter"
    assert version["draft"] == "draft 2 - shorter"
    assert version["final"] == "final 2"
    assert version["final_char_count"] == 7
    assert version["final_char_limit"] == 3000


def _system(prompt: str) -> dict:
    return {"role": "system", "content": [{"type": "text", "text": prompt}]}


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


def _assistant(content: str) -> dict:
    return {"role": "assistant", "content": content}


def _framed(feedback: str) -> str:
    """pumpkit-v6's feedback message, typed out here so a drift in the port fails the test."""
    return (
        "Change the post you just wrote according to this feedback, and change nothing else. "
        "Keep every part the feedback does not ask about exactly as it is, and return the whole "
        "post rather than only the part that changed.\n\n"
        f"The feedback:\n{feedback}"
    )


LEVELSIO_CORPUS = (
    "Below are real posts by the writers whose voice you are reproducing, grouped by author. "
    "They are examples of HOW to write, never of what to write about.\n\n"
    '<creator handle="levelsio">\n'
    "<post>levelsio post 0</post>\n"
    "<post>levelsio post 1</post>\n"
    "</creator>"
)


async def test_the_revision_call_continues_the_conversation_with_finals_and_feedback(
    client, post_id, fake_llm
):
    fake_llm.replies = [
        {"post": "draft 2"},
        {"post": "final 2"},
        {"post": "draft 3"},
        {"post": "final 3"},
    ]

    await client.post(_versions_url(post_id), json={"feedback": "shorter"})
    await client.post(_versions_url(post_id), json={"feedback": "  warmer\n"})

    first_revision, _, second_revision, _ = fake_llm.calls
    assert first_revision.model == REVISING_MODEL
    assert first_revision.response_model.__name__ == "revised_post"
    assert first_revision.messages == [
        _system(DRAFT_POST_PROMPT),
        _user(LEVELSIO_CORPUS),
        _user("ship small things"),
        _assistant("final 1"),
        _user(_framed("shorter")),
    ]
    assert second_revision.messages == [
        _system(DRAFT_POST_PROMPT),
        _user(LEVELSIO_CORPUS),
        _user("ship small things"),
        _assistant("final 1"),
        _user(_framed("shorter")),
        _assistant("final 2"),
        _user(_framed("warmer")),
    ]


async def test_the_humanizer_gets_the_original_brief_and_the_scrubbed_revision(
    client, post_id, fake_llm
):
    fake_llm.replies = [{"post": "it’s shorter—now"}, {"post": "final 2"}]

    await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    humanizer_call = fake_llm.calls[1]
    assert humanizer_call.model == HUMANIZING_MODEL
    assert humanizer_call.messages[0] == _system(HUMANIZER_PROMPT)
    assert humanizer_call.messages[1] == _user(LEVELSIO_CORPUS)
    assert "<brief>\nship small things\n</brief>" in humanizer_call.messages[2]["content"]
    assert humanizer_call.messages[3] == _user("it's shorter - now")
    assert len(humanizer_call.messages) == 4


async def test_the_revision_uses_the_posts_corpus_after_the_users_authors_change(
    client, post_id, fake_x_reader, fake_llm
):
    await client.delete(f"{AUTHORS}/levelsio")
    fake_x_reader.posts["paulg"] = _posts("paulg", 1)
    assert (await client.post(AUTHORS, json={"handle": "paulg"})).status_code == 201
    fake_llm.replies = [{"post": "draft 2"}, {"post": "final 2"}]

    response = await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    assert response.status_code == 201
    assert fake_llm.calls[0].messages[1] == _user(LEVELSIO_CORPUS)
    assert fake_llm.calls[1].messages[1] == _user(LEVELSIO_CORPUS)


async def test_feedback_over_100000_characters_returns_422_without_calling_the_model(
    client, post_id, fake_llm
):
    response = await client.post(_versions_url(post_id), json={"feedback": "a" * 100_001})

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_feedback_of_exactly_100000_characters_is_accepted(client, post_id, fake_llm):
    fake_llm.replies = [{"post": "draft 2"}, {"post": "final 2"}]

    response = await client.post(_versions_url(post_id), json={"feedback": "a" * 100_000})

    assert response.status_code == 201


async def test_blank_feedback_returns_422(client, post_id, fake_llm):
    response = await client.post(_versions_url(post_id), json={"feedback": " \n "})

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_feedback_on_another_users_post_returns_404(client, db, subscribed, fake_llm, clock):
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.flush()
    bobs_post = Post(user_id=bob.id, brief="bob's", corpus_post_ids=[], created_at=clock())
    db.add(bobs_post)
    await db.commit()

    response = await client.post(_versions_url(bobs_post.id), json={"feedback": "shorter"})

    assert response.status_code == 404
    assert fake_llm.calls == []


async def test_feedback_on_a_post_that_does_not_exist_returns_404(client, subscribed, fake_llm):
    response = await client.post(_versions_url("post_missing"), json={"feedback": "shorter"})

    assert response.status_code == 404


async def test_a_user_who_is_not_subscribed_gets_403(client, post_id, db, subscribed, fake_llm):
    await db.delete(subscribed)
    await db.commit()

    response = await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    assert response.status_code == 403
    assert fake_llm.calls == []


async def test_feedback_on_a_post_with_no_version_returns_409(
    client, db, subscribed, fake_x_reader, fake_llm
):
    fake_x_reader.posts["levelsio"] = _posts("levelsio", 1)
    await client.post(AUTHORS, json={"handle": "levelsio"})
    fake_llm.replies = [LLMError("provider down")]
    await client.post(POSTS, json={"brief": "ship"})
    failed_post_id = (await db.execute(select(Post.id))).scalar_one()

    response = await client.post(_versions_url(failed_post_id), json={"feedback": "shorter"})

    assert response.status_code == 409
    assert len(fake_llm.calls) == 1


async def _stored_post(db, post_id: str) -> Post:
    result = await db.execute(
        select(Post).where(Post.id == post_id).options(selectinload(Post.attempts))
    )
    return result.scalar_one()


async def test_a_failed_revision_is_stored_as_a_failed_attempt_and_returns_502(
    client, db, post_id, fake_llm, assert_reported_502, clock
):
    fake_llm.replies = [{"post": "draft 2"}, LLMError("provider timed out")]

    response = await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    assert_reported_502(response)
    post = await _stored_post(db, post_id)
    assert [a.status for a in post.attempts] == ["succeeded", "failed"]
    failed = post.attempts[1]
    assert failed.sequence == 2
    assert failed.feedback == "shorter"
    assert failed.error == "LLMError: provider timed out"
    assert (failed.version_number, failed.final) == (None, None)
    assert as_utc(failed.created_at) == clock()


async def test_a_failed_attempt_stays_out_of_the_conversation_and_the_numbering(
    client, db, post_id, fake_llm
):
    fake_llm.replies = [LLMError("provider down"), {"post": "draft 2"}, {"post": "final 2"}]
    await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    response = await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    assert response.json()["number"] == 2
    assert fake_llm.calls[1].messages[2:] == [
        _user("ship small things"),
        _assistant("final 1"),
        _user(_framed("shorter")),
    ]
    post = await _stored_post(db, post_id)
    assert [(a.sequence, a.version_number) for a in post.attempts] == [(1, 1), (2, None), (3, 2)]


async def test_a_version_stores_its_feedback_models_and_usage(client, db, post_id, fake_llm):
    fake_llm.replies = [{"post": "draft 2"}, {"post": "final 2"}]

    await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    post = await _stored_post(db, post_id)
    version = post.attempts[1]
    assert (version.feedback, version.draft, version.final) == ("shorter", "draft 2", "final 2")
    assert (version.writing_model, version.humanizing_model) == (REVISING_MODEL, HUMANIZING_MODEL)
    assert version.writing_usage is not None and version.humanizing_usage is not None
