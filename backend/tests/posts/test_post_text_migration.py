"""
Migration 0020 gives every existing Post its Text from its latest Version (ADR 0016), read back
through `GET /posts/{id}` and `get_post` as an upgraded Instance would serve it.
"""

import pytest
import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from pumpkit.x_connection.x_length import X_POST_MAX_CHARS
from tests.migrations import insert, migrate

POSTS = "/api/v1/posts"
WRITTEN_AT = "2026-10-01 12:00:00"


async def _to_0019(db_engine) -> None:
    """Take the test schema, built at head, back to before the Text."""
    await migrate(db_engine, lambda config: command.stamp(config, "0020"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0019"))


def _post(connection: Connection, *, user_id: str, post_id: str) -> None:
    insert(
        connection,
        "posts",
        id=post_id,
        user_id=user_id,
        brief="ship",
        corpus_post_ids="[]",
        created_at=WRITTEN_AT,
    )


def _attempt(
    connection: Connection,
    *,
    post_id: str,
    sequence: int,
    number,
    format: str,
    parts,
    status="succeeded",
) -> None:
    insert(
        connection,
        "version_attempts",
        id=f"{post_id}-attempt-{sequence}",
        post_id=post_id,
        sequence=sequence,
        version_number=number,
        feedback=None if sequence == 1 else "again",
        format=format,
        status=status,
        parts=parts,
        created_at=WRITTEN_AT,
    )


@pytest.fixture
async def posts_before_the_text(db_engine, user) -> None:
    """
    At 0019: `post_a` with a single post then a Thread and a failed attempt after them, and
    `post_b` whose only attempt failed.
    """
    await _to_0019(db_engine)

    def fill(connection: Connection) -> None:
        _post(connection, user_id=user.id, post_id="post_a")
        _attempt(
            connection, post_id="post_a", sequence=1, number=1, format="post", parts='["One."]'
        )
        _attempt(
            connection,
            post_id="post_a",
            sequence=2,
            number=2,
            format="thread",
            parts='["Two a.", "Two b."]',
        )
        _attempt(
            connection,
            post_id="post_a",
            sequence=3,
            number=None,
            format="post",
            parts=None,
            status="failed",
        )
        _post(connection, user_id=user.id, post_id="post_b")
        _attempt(
            connection,
            post_id="post_b",
            sequence=1,
            number=None,
            format="post",
            parts=None,
            status="failed",
        )

    async with db_engine.begin() as connection:
        await connection.run_sync(fill)


async def test_the_migration_sets_each_posts_text_to_its_latest_version(
    db_engine, posts_before_the_text, subscribed, client, mcp
):
    await migrate(db_engine, lambda config: command.upgrade(config, "0020"))

    read = (await client.get(f"{POSTS}/post_a")).json()
    tool_read = (await mcp.call_tool("get_post", post_id="post_a"))["structuredContent"]

    expected = {
        "format": "thread",
        "parts": [
            {"text": "Two a.", "char_count": 6, "char_limit": X_POST_MAX_CHARS},
            {"text": "Two b.", "char_count": 6, "char_limit": X_POST_MAX_CHARS},
        ],
        "version_number": 2,
        "edited": False,
    }
    assert read["text"] == expected
    assert tool_read["text"] == expected
    assert [v["number"] for v in read["versions"]] == [1, 2]


async def test_the_migration_leaves_a_post_with_no_version_without_text(
    db_engine, posts_before_the_text, subscribed, client
):
    await migrate(db_engine, lambda config: command.upgrade(config, "0020"))

    read = (await client.get(f"{POSTS}/post_b")).json()

    assert (read["text"], read["versions"]) == (None, [])


async def test_the_migration_runs_down_and_up_again(
    db_engine, posts_before_the_text, subscribed, client
):
    await migrate(db_engine, lambda config: command.upgrade(config, "0020"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0019"))

    def post_columns(connection: Connection) -> set[str]:
        return {column["name"] for column in sa.inspect(connection).get_columns("posts")}

    async with db_engine.connect() as connection:
        assert not {c for c in await connection.run_sync(post_columns) if c.startswith("text_")}

    await migrate(db_engine, lambda config: command.upgrade(config, "0020"))
    read = (await client.get(f"{POSTS}/post_a")).json()
    assert read["text"]["version_number"] == 2
