"""A Post belongs to one Idea of a Brief, which holds the text the User wrote (ADR 0025)."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from pumpkit.auth.models import User
from pumpkit.auth.service import users
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.core.llm import LLMError
from pumpkit.posts.models import Brief, Idea, Post
from tests.connected_apps.conftest import foreign_keys_session as foreign_keys_session
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import written

AUTHORS = "/api/v1/inspiration-authors"
POSTS = "/api/v1/posts"
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.fixture
async def with_author(client, subscribed, fake_x_reader):
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    await save_positioning(client)
    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201


async def _stored(db) -> list[tuple[str, str, int, str]]:
    """Each stored Idea as its Brief's User and text, its posting order and its Post's id."""
    rows = await db.execute(
        select(Brief.user_id, Brief.text, Idea.posting_order, Post.id)
        .join(Idea, Idea.brief_id == Brief.id)
        .outerjoin(Post, Post.idea_id == Idea.id)
    )
    return [tuple(row) for row in rows.all()]


async def test_starting_a_post_stores_its_brief_with_one_idea_the_post_belongs_to(
    client, with_author, fake_llm, db, user
):
    fake_llm.replies = [written("the sketch"), {"post": "the final"}]

    started = (await client.post(POSTS, json={"brief": "ship small things"})).json()

    assert await _stored(db) == [(user.id, "ship small things", 1, started["id"])]


async def test_a_post_whose_first_version_failed_still_has_its_brief(
    client, with_author, fake_llm, db
):
    fake_llm.replies = [LLMError("no reply")]

    assert (await client.post(POSTS, json={"brief": "ship small things"})).status_code == 502

    assert [(text, order) for _, text, order, _ in await _stored(db)] == [("ship small things", 1)]


async def test_each_post_started_gets_a_brief_of_its_own(client, with_author, fake_llm, db):
    fake_llm.replies = [written("one"), {"post": "one"}, written("two"), {"post": "two"}]

    first = (await client.post(POSTS, json={"brief": "the same words"})).json()
    second = (await client.post(POSTS, json={"brief": "the same words"})).json()

    assert sorted(post_id for *_, post_id in await _stored(db)) == sorted(
        [first["id"], second["id"]]
    )
    assert await db.scalar(select(func.count()).select_from(Brief)) == 2


async def test_an_idea_has_at_most_one_post(db, post_with):
    post = await db.get(Post, await post_with("One."))
    assert post is not None
    db.add(Post(user_id=post.user_id, idea_id=post.idea_id, created_at=post.created_at))

    with pytest.raises(IntegrityError):
        await db.flush()


async def test_a_post_built_with_its_user_gives_its_brief_that_user(db, user):
    post = Post(user=user, brief="ship small things", created_at=NOW, text_media=[])
    db.add(post)
    await db.commit()

    assert await _stored(db) == [(user.id, "ship small things", 1, post.id)]


async def test_deleting_a_user_deletes_their_briefs_and_ideas(foreign_keys_session):
    db = foreign_keys_session
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    leaving = User(email="leaving@example.com", display_name="Leaving")
    staying = User(email="staying@example.com", display_name="Staying")
    db.add_all([leaving, staying])
    await db.flush()
    db.add_all(
        [
            Post(user_id=leaving.id, brief="mine", created_at=now, text_media=[]),
            Post(user_id=staying.id, brief="theirs", created_at=now, text_media=[]),
        ]
    )
    await db.commit()

    await users.delete_account(db, leaving)
    await db.commit()

    assert [(user_id, text) for user_id, text, _, _ in await _stored(db)] == [
        (staying.id, "theirs")
    ]
    assert list(await db.scalars(select(Brief.text))) == ["theirs"]
    assert await db.scalar(select(func.count()).select_from(Idea)) == 1
