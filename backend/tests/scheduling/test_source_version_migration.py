"""
Migration 0021 drops each Scheduled post's link to a source Version, since it is copied from its
Post's Text (ADR 0016), and keeps every Scheduled post.
"""

import pytest
import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from tests.migrations import insert, migrate

POSTS = "/api/v1/posts"
WRITTEN_AT = "2026-10-01 12:00:00"
PUBLISH_AT = "2026-10-11 09:00:00"


def _columns(connection: Connection) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns("scheduled_posts")}


@pytest.fixture
async def scheduled_with_its_source_version(db_engine, user) -> None:
    """At 0020: a Post with two Versions, its Scheduled post copied from Version 1."""
    await migrate(db_engine, lambda config: command.stamp(config, "0021"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0020"))

    def fill(connection: Connection) -> None:
        insert(
            connection,
            "posts",
            id="post_a",
            user_id=user.id,
            brief="ship",
            corpus_post_ids="[]",
            created_at=WRITTEN_AT,
            text_format="post",
            text_parts='["Two."]',
            text_version_number=2,
            text_edited=False,
        )
        for number in (1, 2):
            insert(
                connection,
                "version_attempts",
                id=f"version_{number}",
                post_id="post_a",
                sequence=number,
                version_number=number,
                feedback=None if number == 1 else "again",
                format="post",
                status="succeeded",
                parts='["One."]' if number == 1 else '["Two."]',
                created_at=WRITTEN_AT,
            )
        insert(
            connection,
            "scheduled_posts",
            id="scheduled_post_a",
            user_id=user.id,
            x_user_id="1001",
            share_with_followers=False,
            publish_at=PUBLISH_AT,
            state="scheduled",
            source_version_id="version_1",
            post_id="post_a",
            retry_count=0,
            created_at=WRITTEN_AT,
            updated_at=WRITTEN_AT,
        )
        insert(
            connection,
            "scheduled_post_parts",
            id="scheduled_post_part_a",
            scheduled_post_id="scheduled_post_a",
            position=0,
            text="One, edited.",
        )

    async with db_engine.begin() as connection:
        await connection.run_sync(fill)


async def test_the_migration_drops_the_source_version_and_keeps_the_scheduled_post(
    db_engine, scheduled_with_its_source_version, subscribed, client
):
    await migrate(db_engine, lambda config: command.upgrade(config, "0021"))

    read = (await client.get(f"{POSTS}/post_a")).json()

    assert read["status"] == "scheduled"
    assert read["scheduled_post"]["id"] == "scheduled_post_a"
    assert [p["text"] for p in read["scheduled_post"]["parts"]] == ["One, edited."]
    assert "source_version_id" not in read["scheduled_post"]
    async with db_engine.connect() as connection:
        assert "source_version_id" not in await connection.run_sync(_columns)


async def test_the_migration_runs_down_and_up_again(
    db_engine, scheduled_with_its_source_version, subscribed, client
):
    await migrate(db_engine, lambda config: command.upgrade(config, "0021"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0020"))

    def sources(connection: Connection) -> list[tuple[str, str]]:
        rows = connection.execute(sa.text("SELECT id, source_version_id FROM scheduled_posts"))
        return [(row[0], row[1]) for row in rows]

    async with db_engine.connect() as connection:
        assert await connection.run_sync(sources) == [("scheduled_post_a", "version_2")]

    await migrate(db_engine, lambda config: command.upgrade(config, "0021"))
    read = (await client.get(f"{POSTS}/post_a")).json()
    assert read["scheduled_post"]["id"] == "scheduled_post_a"
