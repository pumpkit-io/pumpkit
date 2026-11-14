"""
Migration 0066 names each attempt's User, so the attempts of a discarded Post keep counting once
it has none. Downgrading can't keep those attempts, so it refuses while any exist.
"""

import pytest
import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from tests.migrations import migrate

POSTS = "/api/v1/posts"


def _attempts(connection: Connection) -> list[tuple]:
    rows = connection.execute(sa.text("SELECT post_id, user_id FROM version_attempts"))
    return sorted(tuple(row) for row in rows)


def _columns(connection: Connection) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns("version_attempts")}


async def test_upgrade_names_each_attempts_user_after_a_downgrade(
    db_engine, user, subscribed, post_with
):
    kept = await post_with("Kept.")
    await migrate(db_engine, lambda config: command.stamp(config, "head"))

    await migrate(db_engine, lambda config: command.downgrade(config, "0065"))
    async with db_engine.connect() as connection:
        assert "user_id" not in await connection.run_sync(_columns)

    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    async with db_engine.connect() as connection:
        assert await connection.run_sync(_attempts) == [(kept, user.id)]


async def test_downgrade_refuses_while_a_discarded_posts_attempts_are_kept(
    db_engine, client, user, subscribed, post_with
):
    kept = await post_with("Kept.")
    discarded = await post_with("Discarded.")
    assert (await client.delete(f"{POSTS}/{discarded}")).status_code == 204
    await migrate(db_engine, lambda config: command.stamp(config, "head"))

    with pytest.raises(RuntimeError, match="discarded posts"):
        await migrate(db_engine, lambda config: command.downgrade(config, "0065"))

    async with db_engine.connect() as connection:
        rows = await connection.execute(sa.text("SELECT post_id FROM version_attempts"))
        assert {row[0] for row in rows} == {kept, None}
