from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pumpkit.authors import mediator as authors_mediator
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.core.llm import LLMError
from pumpkit.core.llm_client import LLMNotConfiguredError
from pumpkit.core.time import as_utc
from pumpkit.posts.models import Post
from pumpkit.x_connection.x_length import X_POST_MAX_CHARS
from tests.positioning.positioning import save_positioning
from tests.posts.feedback import written_version
from tests.posts.writing_replies import start_thread, started_post_id, written_post

POSTS = "/api/v1/posts"
BRIEFS = "/api/v1/briefs"
# The model the merge and the humanizer were tuned against, unless a setting says otherwise.
DEFAULT_MODEL = "openai/gpt-6.1-terra"


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
async def with_positioning(client, subscribed):
    """A Positioning saved, which writing a Post needs."""
    await save_positioning(client)


async def test_starting_a_post_returns_it_with_its_first_version(
    client, with_positioning, fake_llm, fixed_clock
):
    fake_llm.replies = [{"post": "the final"}]

    response = await client.post(BRIEFS, json={"brief": "ship small things"})

    body = await written_post(client, response)
    assert body["id"].startswith("post_")
    assert body["brief"] == "ship small things"
    assert body["versions"][0]["id"].startswith("version_attempt_")
    assert body["versions"] == [
        {
            "id": body["versions"][0]["id"],
            "number": 1,
            "feedback": None,
            "format": "post",
            "parts": [{"text": "the final", "char_count": 9, "char_limit": X_POST_MAX_CHARS}],
            "first_reply": False,
            "starting_text": None,
            "created_at": "2026-10-10T12:00:30Z",
        }
    ]


async def test_a_version_response_has_the_versions_text_and_no_sketch(
    client, with_positioning, fake_llm
):
    fake_llm.replies = [
        {"post": "final one"},
        {"post": "final two"},
    ]
    post = await written_post(client, await client.post(BRIEFS, json={"brief": "ship"}))
    [first] = post["versions"]

    second = await written_version(client, post["id"], "shorter")

    for version in (first, second):
        assert set(version) == {
            "id",
            "number",
            "feedback",
            "format",
            "parts",
            "first_reply",
            "starting_text",
            "created_at",
        }
        assert "sketch" not in str(version)


async def test_no_version_is_written_from_the_inspiration_authors_posts(
    client, db, user, with_positioning, fake_x_reader, fake_llm, clock
):
    # The routes are inactive (ADR 0024): a User keeps only authors added before they were.
    fake_x_reader.posts["levelsio"] = _posts("levelsio", 2)
    await authors_mediator.add_author(
        db=db, reader=fake_x_reader, user=user, handle="levelsio", now=clock()
    )
    await db.commit()
    post_id = started_post_id(await start_thread(client, fake_llm, ["a", "b"], brief="ship"))
    fake_llm.replies = [{"parts": ["c", "d"]}, {"post": "one"}, {"post": "two"}]
    for body in ({"feedback": "shorter"}, {"feedback": "condense", "format": "post"}):
        response = await client.post(f"{POSTS}/{post_id}/versions", json=body)
        assert response.status_code == 202, response.text
    fake_llm.replies = [{"post": "a post"}]
    assert (await client.post(BRIEFS, json={"brief": "ship"})).status_code == 201

    prompts = "\n".join(str(m["content"]) for call in fake_llm.calls for m in call.messages)
    assert "levelsio" not in prompts
    assert [post.corpus_post_ids for post in await _stored_posts(db)] == [None, None]


async def test_the_final_is_counted_as_x_counts_it_and_kept_when_over_the_limit(
    client, with_positioning, fake_llm
):
    # X counts an emoji as 2.
    long_final = "🚀" + "a" * 300
    fake_llm.replies = [{"post": long_final}]

    response = await client.post(BRIEFS, json={"brief": "ship"})

    version = (await written_post(client, response))["versions"][0]
    assert version["parts"] == [
        {"text": long_final, "char_count": 302, "char_limit": X_POST_MAX_CHARS}
    ]


async def test_a_brief_over_200000_characters_returns_422_without_calling_the_model(
    client, with_positioning, fake_llm
):
    response = await client.post(BRIEFS, json={"brief": "a" * 200_001})

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_a_brief_of_exactly_200000_characters_is_accepted(client, with_positioning, fake_llm):
    fake_llm.replies = [{"post": "final"}]

    response = await client.post(BRIEFS, json={"brief": "a" * 200_000})

    assert response.status_code == 201


async def test_a_blank_brief_returns_422(client, with_positioning, fake_llm):
    response = await client.post(BRIEFS, json={"brief": "  \n "})

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_a_user_who_is_not_subscribed_gets_403(client, fake_llm):
    response = await client.post(BRIEFS, json={"brief": "ship"})

    assert response.status_code == 403
    assert fake_llm.calls == []


async def test_a_user_without_a_subscription_writes_a_post_where_no_plans_are_sold(
    client, sells_no_plans, fake_x_reader, fake_llm
):
    await save_positioning(client)
    fake_llm.replies = [{"post": "final"}]

    response = await client.post(BRIEFS, json={"brief": "ship"})

    assert (await written_post(client, response))["versions"][0]["parts"][0]["text"] == "final"


async def _stored_posts(db) -> list[Post]:
    result = await db.execute(select(Post).options(selectinload(Post.attempts)))
    return list(result.scalars())


async def test_a_post_stores_its_brief_and_version_with_models_and_usage(
    client, db, with_positioning, fake_llm, clock
):
    fake_llm.replies = [{"post": "final"}]

    response = await client.post(BRIEFS, json={"brief": "ship"})

    [post] = await _stored_posts(db)
    assert post.id == started_post_id(response)
    assert post.brief == "ship"
    assert post.corpus_post_ids is None
    [attempt] = post.attempts
    assert attempt.status == "succeeded"
    assert (attempt.format, attempt.sketch_parts, attempt.parts) == (
        "post",
        ["The merged sketch."],
        ["final"],
    )
    assert (attempt.sketch_model, attempt.humanizing_model) == (DEFAULT_MODEL, DEFAULT_MODEL)
    assert attempt.sketch_usage == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }
    assert attempt.humanizing_usage == attempt.sketch_usage
    assert attempt.error is None
    assert as_utc(attempt.created_at) == clock()


async def test_a_failed_version_stores_the_post_and_a_failed_attempt_and_reports_it(
    client, db, with_positioning, fake_llm, fake_posthog
):
    fake_llm.replies = [LLMError("provider timed out")]

    response = await client.post(BRIEFS, json={"brief": "ship"})

    assert (await written_post(client, response))["writing_state"] == "not_written"
    fake_posthog.capture_exception.assert_called_once()
    [post] = await _stored_posts(db)
    assert post.brief == "ship"
    [attempt] = post.attempts
    assert attempt.status == "failed"
    assert attempt.error == "LLMError: provider timed out"
    assert (attempt.sketch_parts, attempt.parts, attempt.version_number) == (None, None, None)
    assert attempt.format == "post"


async def test_retrying_after_a_failure_starts_a_new_post(client, db, with_positioning, fake_llm):
    fake_llm.replies = [LLMError("provider down"), {"post": "final"}]
    await client.post(BRIEFS, json={"brief": "ship"})

    response = await client.post(BRIEFS, json={"brief": "ship"})

    assert response.status_code == 201
    posts = await _stored_posts(db)
    assert len(posts) == 2
    assert sorted(p.attempts[0].status for p in posts) == ["failed", "succeeded"]


async def test_a_write_without_the_llm_key_leaves_the_post_not_written_and_stores_the_attempt(
    client, db, with_positioning, fake_llm
):
    fake_llm.replies = [LLMNotConfiguredError("LLM_API_KEY is not set. Add it to .env.")]

    response = await client.post(BRIEFS, json={"brief": "ship"})

    assert (await written_post(client, response))["writing_state"] == "not_written"
    [post] = await _stored_posts(db)
    assert post.attempts[0].status == "failed"
