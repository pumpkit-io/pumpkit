"""
`one_idea_a_day` in `GET /posts/{id}`: when another Post of the same Brief has a Scheduled post
that goes or went out, the latest of their times, from which "Post to…" presets the next day.
"""

import pytest

from pumpkit.core.db.session import get_session_maker
from pumpkit.main import app
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import HUMANIZED_POST, POST_IDEAS, ideas, planned_post

BRIEFS = "/api/v1/briefs"
POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
CORE_IDEAS = ["Pain first.", "Charge 20 euros.", "Skip OAuth."]


@pytest.fixture
async def ready(client, subscribed, connect_x, fixed_clock, writing_session_maker, fake_llm):
    await connect_x()
    await save_positioning(client)
    app.dependency_overrides[get_session_maker] = lambda: writing_session_maker
    fake_llm.standing[POST_IDEAS] = ideas(
        planned_post("Three lessons."), [planned_post(core_idea) for core_idea in CORE_IDEAS]
    )
    fake_llm.standing[HUMANIZED_POST] = {"post": "A lesson.", "first_reply": None}


async def _split_posts(client) -> list[str]:
    """Plans a Brief and writes its three split Ideas: their Posts' ids, in the Brief's order."""
    planned = await client.post(BRIEFS, json={"brief": "Three things I learned."})
    assert planned.status_code == 201, planned.text
    split = [idea["id"] for idea in planned.json()["ideas"] if not idea["whole_brief"]]
    written = await client.post(f"{BRIEFS}/{planned.json()['id']}/posts", json={"idea_ids": split})
    assert written.status_code == 202, written.text
    return [idea["post"]["id"] for idea in written.json()["ideas"] if idea["post"]]


async def _schedule(client, post_id: str, **when) -> None:
    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, **when})
    assert response.status_code == 201, response.text


async def _one_idea_a_day(client, post_id: str):
    response = await client.get(f"{POSTS}/{post_id}")
    assert response.status_code == 200, response.text
    return response.json()["one_idea_a_day"]


async def test_no_other_scheduled_post_of_the_brief_gives_none(client, ready):
    first, _, _ = await _split_posts(client)

    assert await _one_idea_a_day(client, first) is None


async def test_the_posts_own_scheduled_post_does_not_count(client, ready):
    first, _, _ = await _split_posts(client)
    await _schedule(client, first, publish_at="2026-10-11T09:00:00Z")

    assert await _one_idea_a_day(client, first) is None


async def test_another_ideas_scheduled_post_gives_its_time(client, ready):
    first, second, _ = await _split_posts(client)
    await _schedule(client, first, publish_at="2026-10-11T09:00:00Z")

    assert await _one_idea_a_day(client, second) == "2026-10-11T09:00:00Z"


async def test_of_several_the_latest_wins(client, ready):
    first, second, third = await _split_posts(client)
    await _schedule(client, second, publish_at="2026-10-13T09:00:00Z")
    await _schedule(client, first, publish_at="2026-10-11T09:00:00Z")

    assert await _one_idea_a_day(client, third) == "2026-10-13T09:00:00Z"


async def test_a_published_post_counts(client, ready):
    first, second, _ = await _split_posts(client)
    await _schedule(client, first, publish_now=True)

    assert await _one_idea_a_day(client, second) == "2026-10-10T12:00:00Z"


async def test_another_briefs_scheduled_post_does_not_count(client, ready):
    other, _, _ = await _split_posts(client)
    await _schedule(client, other, publish_at="2026-10-11T09:00:00Z")
    first, _, _ = await _split_posts(client)

    assert await _one_idea_a_day(client, first) is None
