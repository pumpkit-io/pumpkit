"""Migration 0064 keeps the Feedback being written on its Post, to show it once it fails."""

import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from tests.migrations import migrate

POSTS = "/api/v1/posts"
COLUMNS = {"unwritten_feedback", "unwritten_feedback_format"}


def _columns(connection: Connection) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns("posts")}


async def test_downgrade_drops_the_feedback_and_upgrade_reads_an_earlier_post_with_no_failure(
    db_engine, client, subscribed, post_with
):
    post_id = await post_with("Written before failures showed.")
    await migrate(db_engine, lambda config: command.stamp(config, "head"))

    await migrate(db_engine, lambda config: command.downgrade(config, "0063"))
    async with db_engine.connect() as connection:
        assert not COLUMNS & await connection.run_sync(_columns)

    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    async with db_engine.connect() as connection:
        assert COLUMNS <= await connection.run_sync(_columns)
    assert (await client.get(f"{POSTS}/{post_id}")).json()["failed_feedback"] is None
