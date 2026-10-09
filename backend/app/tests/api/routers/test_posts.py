from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.datetimes import as_utc
from app.core.llm import LLMError
from app.core.openrouter import LLMNotConfiguredError
from app.core.x_reader import FetchedPost
from app.db.models import InspirationAuthor, Post
from app.writing.constants import HUMANIZING_MODEL, WRITING_MODEL
from app.writing.prompts.draft_post import DRAFT_POST_PROMPT
from app.writing.prompts.humanizer import HUMANIZER_PROMPT

AUTHORS = "/api/v1/inspiration-authors"
POSTS = "/api/v1/posts"


def _posts(handle: str, count: int) -> list[FetchedPost]:
    """`count` original posts with ids `<handle>-<n>`, the first newest."""
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return [
        FetchedPost(
            post_id=f"{handle}-{n}", text=f"{handle} post {n}", posted_at=start - timedelta(hours=n)
        )
        for n in range(count)
    ]


@pytest.fixture
async def with_author(client, subscribed, fake_x_reader):
    """`levelsio` on the User's list, with two stored posts."""
    fake_x_reader.posts["levelsio"] = _posts("levelsio", 2)
    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201


async def test_starting_a_post_returns_it_with_its_first_version(client, with_author, fake_llm):
    fake_llm.replies = [{"post": "the draft—with a dash"}, {"post": "the final"}]

    response = await client.post(POSTS, json={"brief": "ship small things"})

    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("post_")
    assert body["brief"] == "ship small things"
    assert body["versions"] == [
        {
            "number": 1,
            "feedback": None,
            "draft": "the draft - with a dash",
            "final": "the final",
            "final_char_count": 9,
            "final_char_limit": 3000,
            "tells": [],
        }
    ]


async def test_a_version_reports_the_tells_the_slop_check_found_in_its_final(
    client, db, with_author, fake_llm
):
    fake_llm.replies = [
        {"post": "draft"},
        {"post": "the unfair advantage was distribution — and this is why i keep saying it"},
    ]

    response = await client.post(POSTS, json={"brief": "ship"})

    tells = [
        {"name": "em_dash", "description": "em dash"},
        {"name": "invented_stance", "description": "invented recurring opinion"},
        {"name": "startup_cliche", "description": "startup-commentary cliche"},
    ]
    assert response.json()["versions"][0]["tells"] == tells
    [post] = await _stored_posts(db)
    assert post.attempts[0].slop_tells == tells


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
    "<post>levelsio post 1</post>\n"
    "</creator>"
)


async def test_the_draft_call_gets_the_draft_prompt_then_the_corpus_then_the_brief(
    client, with_author, fake_llm
):
    fake_llm.replies = [{"post": "draft"}, {"post": "final"}]

    await client.post(POSTS, json={"brief": "  ship small things\n"})

    draft_call = fake_llm.calls[0]
    assert draft_call.model == WRITING_MODEL
    assert draft_call.response_model.__name__ == "drafted_post"
    assert draft_call.messages == [
        _system(DRAFT_POST_PROMPT),
        _user(LEVELSIO_CORPUS),
        _user("ship small things"),
    ]


async def test_the_humanizer_gets_its_prompt_the_corpus_the_brief_message_then_the_scrubbed_draft(
    client, with_author, fake_llm
):
    fake_llm.replies = [{"post": "it’s a draft—really"}, {"post": "final"}]

    await client.post(POSTS, json={"brief": "ship small things"})

    humanizer_call = fake_llm.calls[1]
    assert humanizer_call.model == HUMANIZING_MODEL
    assert humanizer_call.response_model.__name__ == "refined_post"
    assert humanizer_call.messages == [
        _system(HUMANIZER_PROMPT),
        _user(LEVELSIO_CORPUS),
        _user(
            "This is the brief the post below was written from. Use it only to keep the "
            "rewrite true to what it asks for - its position and any explicit asks. Do not "
            "add anything from it that the post does not already say.\n\n"
            "<brief>\nship small things\n</brief>"
        ),
        _user("it's a draft - really"),
    ]


async def test_the_corpus_is_the_newest_20_posts_of_each_author_in_list_order(
    client, subscribed, fake_x_reader, fake_llm
):
    fake_x_reader.posts["paulg"] = _posts("paulg", 21)
    fake_x_reader.posts["levelsio"] = _posts("levelsio", 1)
    await client.post(AUTHORS, json={"handle": "paulg"})
    await client.post(AUTHORS, json={"handle": "levelsio"})
    fake_llm.replies = [{"post": "draft"}, {"post": "final"}]

    await client.post(POSTS, json={"brief": "ship"})

    corpus = fake_llm.calls[0].messages[1]["content"]
    assert corpus.count("<post>") == 21
    assert "<post>paulg post 19</post>" in corpus
    assert "paulg post 20<" not in corpus
    assert corpus.index('<creator handle="paulg">') < corpus.index('<creator handle="levelsio">')


async def test_posts_posted_in_the_same_second_are_ordered_by_post_id_descending(
    client, subscribed, fake_x_reader, fake_llm
):
    same_time = datetime(2026, 10, 1, tzinfo=timezone.utc)
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(post_id="aaa", text="lower id", posted_at=same_time),
        FetchedPost(post_id="bbb", text="higher id", posted_at=same_time),
    ]
    await client.post(AUTHORS, json={"handle": "levelsio"})
    fake_llm.replies = [{"post": "draft"}, {"post": "final"}]

    await client.post(POSTS, json={"brief": "ship"})

    corpus = fake_llm.calls[0].messages[1]["content"]
    assert corpus.index("higher id") < corpus.index("lower id")


async def test_the_final_is_counted_in_characters_and_kept_when_over_the_limit(
    client, with_author, fake_llm
):
    long_final = "🚀" + "a" * 3000
    fake_llm.replies = [{"post": "draft"}, {"post": long_final}]

    response = await client.post(POSTS, json={"brief": "ship"})

    version = response.json()["versions"][0]
    assert version["final"] == long_final
    assert version["final_char_count"] == 3001
    assert version["final_char_limit"] == 3000


async def test_a_brief_over_200000_characters_returns_422_without_calling_the_model(
    client, with_author, fake_llm
):
    response = await client.post(POSTS, json={"brief": "a" * 200_001})

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_a_brief_of_exactly_200000_characters_is_accepted(client, with_author, fake_llm):
    fake_llm.replies = [{"post": "draft"}, {"post": "final"}]

    response = await client.post(POSTS, json={"brief": "a" * 200_000})

    assert response.status_code == 201


async def test_a_blank_brief_returns_422(client, with_author, fake_llm):
    response = await client.post(POSTS, json={"brief": "  \n "})

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_starting_a_post_with_no_inspiration_authors_returns_422(
    client, subscribed, fake_llm
):
    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Add an Inspiration author with posts before writing a Post."
    )
    assert fake_llm.calls == []


async def test_starting_a_post_when_no_author_has_stored_posts_returns_422(
    client, db, user, subscribed, fake_llm, clock
):
    db.add(InspirationAuthor(user_id=user.id, handle="quiet", position=0, added_at=clock()))
    await db.commit()

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_a_user_who_is_not_subscribed_gets_403(client, fake_llm):
    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 403
    assert fake_llm.calls == []


async def test_a_user_who_is_not_subscribed_writes_while_subscriptions_are_not_required(
    client, fake_x_reader, fake_llm, monkeypatch
):
    monkeypatch.setattr(settings, "SUBSCRIPTION_REQUIRED", False)
    fake_x_reader.posts["levelsio"] = _posts("levelsio", 2)
    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201
    fake_llm.replies = [{"post": "draft"}, {"post": "final"}]

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 201


async def _stored_posts(db) -> list[Post]:
    result = await db.execute(select(Post).options(selectinload(Post.attempts)))
    return list(result.scalars())


async def test_a_post_stores_its_brief_corpus_and_version_with_models_and_usage(
    client, db, with_author, fake_llm, clock
):
    fake_llm.replies = [{"post": "draft"}, {"post": "final"}]

    response = await client.post(POSTS, json={"brief": "ship"})

    [post] = await _stored_posts(db)
    assert post.id == response.json()["id"]
    assert post.brief == "ship"
    assert post.corpus_post_ids == ["levelsio-0", "levelsio-1"]
    [attempt] = post.attempts
    assert attempt.status == "succeeded"
    assert (attempt.draft, attempt.final, attempt.final_char_count) == ("draft", "final", 5)
    assert (attempt.writing_model, attempt.humanizing_model) == (WRITING_MODEL, HUMANIZING_MODEL)
    assert attempt.writing_usage == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }
    assert attempt.humanizing_usage == attempt.writing_usage
    assert attempt.error is None
    assert as_utc(attempt.created_at) == clock()


async def test_a_post_keeps_its_corpus_when_the_users_authors_change(
    client, db, with_author, fake_x_reader, fake_llm
):
    fake_llm.replies = [{"post": "draft"}, {"post": "final"}]
    await client.post(POSTS, json={"brief": "ship"})

    await client.delete(f"{AUTHORS}/levelsio")
    fake_x_reader.posts["paulg"] = _posts("paulg", 1)
    await client.post(AUTHORS, json={"handle": "paulg"})

    [post] = await _stored_posts(db)
    assert post.corpus_post_ids == ["levelsio-0", "levelsio-1"]


async def test_a_failed_version_stores_the_post_and_a_failed_attempt_and_returns_502(
    client, db, with_author, fake_llm, assert_reported_502
):
    fake_llm.replies = [{"post": "draft"}, LLMError("provider timed out")]

    response = await client.post(POSTS, json={"brief": "ship"})

    assert_reported_502(response)
    assert response.json()["detail"] == "Writing the Post failed. Please try again."
    [post] = await _stored_posts(db)
    assert post.brief == "ship"
    [attempt] = post.attempts
    assert attempt.status == "failed"
    assert attempt.error == "LLMError: provider timed out"
    assert (attempt.draft, attempt.final, attempt.version_number) == (None, None, None)


async def test_retrying_after_a_failure_starts_a_new_post(client, db, with_author, fake_llm):
    fake_llm.replies = [LLMError("provider down"), {"post": "draft"}, {"post": "final"}]
    await client.post(POSTS, json={"brief": "ship"})

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 201
    posts = await _stored_posts(db)
    assert len(posts) == 2
    assert sorted(p.attempts[0].status for p in posts) == ["failed", "succeeded"]


async def test_writing_without_the_openrouter_key_fails_clearly_and_stores_the_attempt(
    client, db, with_author, fake_llm
):
    fake_llm.replies = [
        LLMNotConfiguredError("OPENROUTER_API_KEY is not set. Add it to backend/.env.")
    ]

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 503
    assert "OPENROUTER_API_KEY" in response.json()["detail"]
    [post] = await _stored_posts(db)
    assert post.attempts[0].status == "failed"
