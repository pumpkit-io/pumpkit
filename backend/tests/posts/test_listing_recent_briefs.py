"""
`GET /briefs` lists the User's latest ten Briefs for New post, each with the start of its text and
counts of its Posts by writing state and of the Ideas its page offers (ADR 0025).
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from pumpkit.core.config import settings
from pumpkit.core.db.session import get_session_maker
from pumpkit.core.llm import LLMCall, LLMError
from pumpkit.main import app
from pumpkit.posts.models import Post, VersionAttempt
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import (
    HUMANIZED_POST,
    POST_IDEAS,
    SKETCHED_POST,
    ideas,
    planned_post,
)

BRIEFS = "/api/v1/briefs"
CORE_IDEAS = [
    "Make sure the pain is real before you build.",
    "Charge at least 20 euros a month.",
    "Don't make OAuth integrations your core value.",
]
WHOLE = "Three lessons from a failed SaaS."


@pytest.fixture
async def ready(client, subscribed, writing_session_maker, fixed_clock):
    await save_positioning(client)
    # Writes in parallel record their Versions at once, which SQLite takes only as write transactions.
    app.dependency_overrides[get_session_maker] = lambda: writing_session_maker
    return fixed_clock


def _humanizer(fails: tuple[str, ...] = ()):
    def reply(call: LLMCall):
        text = "\n".join(str(message["content"]) for message in call.messages)
        for core_idea in [*CORE_IDEAS, WHOLE]:
            if core_idea in text:
                if core_idea in fails:
                    return LLMError("provider down")
                return {"post": f"Post on: {core_idea}", "first_reply": None}
        raise AssertionError("The humanizer was sent no known core idea")

    return reply


@pytest.fixture
def split(fake_llm):
    fake_llm.standing[POST_IDEAS] = ideas(
        planned_post(WHOLE), [planned_post(core_idea) for core_idea in CORE_IDEAS]
    )
    fake_llm.standing[HUMANIZED_POST] = _humanizer()


@pytest.fixture
def one_idea(fake_llm):
    fake_llm.standing[POST_IDEAS] = ideas(planned_post(WHOLE))
    fake_llm.standing[HUMANIZED_POST] = _humanizer()


async def _plan(client, brief: str = "Three things I learned from my SaaS.") -> dict:
    response = await client.post(BRIEFS, json={"brief": brief})
    assert response.status_code == 201, response.text
    return response.json()


async def _write(client, brief: dict, ideas: list[dict]) -> list[str]:
    """Writes `ideas` and answers with the Brief's Post ids in its order."""
    response = await client.post(
        f"{BRIEFS}/{brief['id']}/posts", json={"idea_ids": [idea["id"] for idea in ideas]}
    )
    assert response.status_code == 202, response.text
    return [idea["post"]["id"] for idea in response.json()["ideas"] if idea["post"]]


def _split(brief: dict) -> list[dict]:
    return [idea for idea in brief["ideas"] if not idea["whole_brief"]]


async def _recent(client) -> list[dict]:
    response = await client.get(BRIEFS)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_a_user_with_no_briefs_has_none_listed(client, ready):
    assert await _recent(client) == []


async def test_a_split_brief_counts_its_posts_by_state_and_the_ideas_still_offered(
    client, ready, fake_llm, split
):
    fake_llm.standing[HUMANIZED_POST] = _humanizer(fails=(CORE_IDEAS[1],))
    planned = await _plan(client)
    first, second, _ = _split(planned)
    post_ids = await _write(client, planned, [first, second])

    assert await _recent(client) == [
        {
            "id": planned["id"],
            "text_start": "Three things I learned from my SaaS.",
            "created_at": "2026-10-10T12:00:30Z",
            "posts_written": 1,
            "posts_writing": 0,
            "posts_not_written": 1,
            "ideas_offered": 1,
            "post_ids": post_ids,
        }
    ]


async def test_a_post_being_written_counts_as_writing(
    client, ready, fake_llm, one_idea, background_tasks
):
    held = asyncio.Event()
    fake_llm.held[SKETCHED_POST] = held
    planned = await _plan(client)

    [brief] = await _recent(client)

    assert brief["posts_writing"] == 1
    assert brief["posts_written"] == 0
    assert brief["post_ids"] == [planned["ideas"][0]["post"]["id"]]
    held.set()
    await background_tasks.wait()
    [brief] = await _recent(client)
    assert (brief["posts_written"], brief["posts_writing"]) == (1, 0)


async def test_a_write_past_the_timeout_counts_as_not_written(
    client, ready, fake_llm, one_idea, background_tasks
):
    held = asyncio.Event()
    fake_llm.held[SKETCHED_POST] = held
    await _plan(client)

    ready.advance(timedelta(minutes=16))

    [brief] = await _recent(client)
    assert (brief["posts_writing"], brief["posts_not_written"]) == (0, 1)
    held.set()
    await background_tasks.wait()


async def test_a_one_idea_brief_written_offers_nothing_and_has_its_one_post(
    client, ready, one_idea
):
    planned = await _plan(client)

    [brief] = await _recent(client)

    assert brief["posts_written"] == 1
    assert brief["ideas_offered"] == 0
    assert brief["post_ids"] == [planned["ideas"][0]["post"]["id"]]


async def test_a_split_brief_not_written_offers_every_split_idea_and_the_whole_brief(
    client, ready, split
):
    await _plan(client)

    [brief] = await _recent(client)

    assert brief["post_ids"] == []
    assert (brief["posts_written"], brief["posts_writing"], brief["posts_not_written"]) == (0, 0, 0)
    assert brief["ideas_offered"] == 4


async def test_once_the_whole_brief_is_written_no_split_idea_is_offered(client, ready, split):
    planned = await _plan(client)
    [whole] = [idea for idea in planned["ideas"] if idea["whole_brief"]]
    await _write(client, planned, [whole])

    [brief] = await _recent(client)

    assert brief["posts_written"] == 1
    assert brief["ideas_offered"] == 0


async def _use_a_generation(db, user_id: str) -> None:
    moment = datetime(2026, 10, 2, tzinfo=timezone.utc)
    post = Post(user_id=user_id, brief="earlier", corpus_post_ids=[], created_at=moment)
    db.add(post)
    await db.flush()
    db.add(
        VersionAttempt(
            post_id=post.id,
            sequence=1,
            version_number=1,
            format="post",
            status="succeeded",
            parts=["earlier"],
            created_at=moment,
        )
    )
    await db.commit()


async def test_a_brief_stored_unwritten_for_want_of_generations_offers_its_idea(
    client, db, user, ready, one_idea, monkeypatch
):
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 1)
    await _use_a_generation(db, user.id)
    planned = await _plan(client)

    briefs = await _recent(client)

    [brief] = [b for b in briefs if b["id"] == planned["id"]]
    assert brief["post_ids"] == []
    assert brief["ideas_offered"] == 1


async def test_the_latest_ten_briefs_are_listed_newest_first(client, ready, split):
    planned = []
    for n in range(11):
        planned.append(await _plan(client, f"Brief number {n}"))
        ready.advance(timedelta(minutes=1))

    briefs = await _recent(client)

    assert [brief["id"] for brief in briefs] == [b["id"] for b in reversed(planned)][:10]


async def test_the_start_of_a_long_brief_is_cut_at_a_word_on_one_line(client, ready, split):
    words = "word " * 200
    await _plan(client, f"so I've been testing\nsomething this week {words}")

    [brief] = await _recent(client)

    assert brief["text_start"].startswith("so I've been testing something this week word")
    assert brief["text_start"].endswith("word…")
    assert len(brief["text_start"]) <= 101


async def test_another_users_briefs_are_not_listed(
    client, ready, split, sign_in_as_another_subscribed_user
):
    await _plan(client)
    await sign_in_as_another_subscribed_user()

    assert await _recent(client) == []


async def test_listing_takes_as_many_queries_for_several_briefs_as_for_one(
    client, ready, fake_llm, split, db_engine
):
    statements: list[str] = []

    def seen(conn, cursor, statement, *args) -> None:
        statements.append(statement)

    async def queries() -> int:
        statements.clear()
        event.listen(db_engine.sync_engine, "before_cursor_execute", seen)
        try:
            await _recent(client)
        finally:
            event.remove(db_engine.sync_engine, "before_cursor_execute", seen)
        return len(statements)

    planned = await _plan(client)
    await _write(client, planned, _split(planned)[:2])
    one = await queries()
    for n in range(5):
        planned = await _plan(client, f"Brief number {n}")
        await _write(client, planned, _split(planned)[:1])

    assert await queries() == one
