"""
Migration 0060 gives every Post an Idea of a Brief holding the text the Post used to store
(ADR 0025), and its downgrade puts the text back on the Post.
"""

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from pumpkit.auth.models import User
from pumpkit.posts.models import Post
from tests.migrations import migrate

POSTS = "/api/v1/posts"
WRITTEN_AT = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)

_POSTS_BEFORE = sa.table(
    "posts",
    sa.column("id", sa.String()),
    sa.column("user_id", sa.String()),
    sa.column("brief", sa.Text()),
    sa.column("corpus_post_ids", sa.JSON()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("text_edited", sa.Boolean()),
)


def _old_post(connection: Connection, *, post_id: str, user_id: str, brief: str) -> None:
    connection.execute(
        _POSTS_BEFORE.insert().values(
            id=post_id,
            user_id=user_id,
            brief=brief,
            corpus_post_ids=["levelsio-0"],
            created_at=WRITTEN_AT,
            text_edited=False,
        )
    )


def _rows(connection: Connection, query: str) -> list[tuple]:
    return [tuple(row) for row in connection.execute(sa.text(query))]


@pytest.fixture
async def bob(db) -> User:
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.commit()
    return bob


@pytest.fixture
async def posts_storing_their_briefs(db_engine, user, bob) -> None:
    """At 0059: `post_a` and `post_b` of `user` and `post_c` of Bob, each storing its Brief."""
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0059"))

    def fill(connection: Connection) -> None:
        _old_post(connection, post_id="post_a", user_id=user.id, brief="ship small things")
        _old_post(connection, post_id="post_b", user_id=user.id, brief="ship small things")
        _old_post(connection, post_id="post_c", user_id=bob.id, brief="bob's")

    async with db_engine.begin() as connection:
        await connection.run_sync(fill)


async def test_upgrade_gives_each_post_an_idea_of_a_brief_of_its_own(
    db_engine, posts_storing_their_briefs, subscribed, client, user, bob
):
    await migrate(db_engine, lambda config: command.upgrade(config, "head"))

    assert (await client.get(f"{POSTS}/post_a")).json()["brief"] == "ship small things"
    async with db_engine.connect() as connection:
        stored = await connection.run_sync(
            _rows,
            "SELECT posts.id, briefs.user_id, briefs.text, ideas.posting_order "
            "FROM posts JOIN ideas ON ideas.id = posts.idea_id "
            "JOIN briefs ON briefs.id = ideas.brief_id ORDER BY posts.id",
        )
        briefs = await connection.run_sync(_rows, "SELECT count(*) FROM briefs")
    assert stored == [
        ("post_a", user.id, "ship small things", 1),
        ("post_b", user.id, "ship small things", 1),
        ("post_c", bob.id, "bob's", 1),
    ]
    assert briefs == [(3,)]


async def test_downgrade_keeps_each_posts_brief_and_gives_a_post_without_a_corpus_an_empty_one(
    db_engine, posts_storing_their_briefs
):
    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    async with db_engine.begin() as connection:
        await connection.execute(
            sa.text("UPDATE posts SET corpus_post_ids = NULL WHERE id = 'post_b'")
        )

    await migrate(db_engine, lambda config: command.downgrade(config, "0059"))

    async with db_engine.connect() as connection:
        posts = await connection.run_sync(
            _rows, "SELECT id, user_id, brief, corpus_post_ids FROM posts ORDER BY id"
        )
    assert [(post_id, brief) for post_id, _, brief, _ in posts] == [
        ("post_a", "ship small things"),
        ("post_b", "ship small things"),
        ("post_c", "bob's"),
    ]
    # SQLite hands the JSON back as text, Postgres as a list.
    assert [corpus for *_, corpus in posts] in (
        [["levelsio-0"], [], ["levelsio-0"]],
        ['["levelsio-0"]', "[]", '["levelsio-0"]'],
    )


async def test_downgrade_gives_a_post_whose_corpus_was_set_to_none_an_empty_one(
    db_engine, posts_storing_their_briefs, db
):
    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    post = await db.get(Post, "post_b")
    assert post is not None
    post.corpus_post_ids = None
    await db.commit()

    await migrate(db_engine, lambda config: command.downgrade(config, "0059"))

    async with db_engine.connect() as connection:
        posts = await connection.run_sync(
            _rows, "SELECT corpus_post_ids FROM posts WHERE id = 'post_b'"
        )
    # SQLite hands the JSON back as text, Postgres as a list.
    assert posts in ([([],)], [("[]",)])


async def test_a_post_started_after_the_upgrade_is_read_back_with_its_brief(
    db_engine, posts_storing_their_briefs, subscribed, client, post_with
):
    await migrate(db_engine, lambda config: command.upgrade(config, "head"))

    post_id = await post_with("One.")

    assert (await client.get(f"{POSTS}/{post_id}")).json()["brief"] == "Seeded"
