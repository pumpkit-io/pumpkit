"""`start_post` and `give_feedback` refuse at the Generations limit as the web routes do."""

from datetime import datetime, timedelta, timezone

import pytest

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.core.config import settings
from pumpkit.posts.models import Post, VersionAttempt
from tests.mcp_client import error_text
from tests.posts.writing_replies import written

REFUSAL = (
    "You've used this period's 2 generations. They reset on 1 November. "
    "Failed attempts don't count. http://localhost:5173/settings"
)


@pytest.fixture
async def with_author(subscribed, mcp, fake_x_reader, monkeypatch):
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 2)
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    assert (await mcp.call_tool("add_inspiration_author", handle="levelsio"))["isError"] is False


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
            created_at=moment + timedelta(minutes=1),
        )
    )
    await db.commit()


async def test_start_post_refuses_with_no_generations_left_and_links_to_settings(
    db, user, with_author, mcp, fake_llm, fixed_clock
):
    await _use_a_generation(db, user.id)
    await _use_a_generation(db, user.id)

    result = await mcp.call_tool("start_post", brief="ship")

    assert result["isError"] is True
    assert error_text(result) == REFUSAL
    assert result["structuredContent"] == {
        "url": "http://localhost:5173/settings",
        "code": "ALLOWANCE_USED_UP",
        "ran_out": "generations",
        "needed": 1,
        "left": 0,
        "resets_at": "2026-11-01T00:00:00Z",
        "way_out": None,
    }
    assert fake_llm.calls == []


async def test_give_feedback_refuses_with_no_generations_left(
    db, user, with_author, mcp, fake_llm, fixed_clock
):
    fake_llm.replies = [written("sketch"), {"post": "final"}]
    post_id = (await mcp.call_tool("start_post", brief="ship"))["structuredContent"]["id"]
    await _use_a_generation(db, user.id)
    fake_llm.calls.clear()

    result = await mcp.call_tool("give_feedback", post_id=post_id, feedback="shorter")

    assert result["isError"] is True
    assert error_text(result) == REFUSAL
    assert fake_llm.calls == []
