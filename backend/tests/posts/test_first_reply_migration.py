"""Migration 0063 records a first reply on the Text, each Version and each Scheduled post."""

import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from tests.migrations import migrate

POSTS = "/api/v1/posts"
COLUMNS = {
    "posts": {"text_first_reply"},
    "version_attempts": {"first_reply", "starting_text_first_reply"},
    "scheduled_posts": {"first_reply"},
}


def _columns(connection: Connection) -> dict[str, set[str]]:
    inspector = sa.inspect(connection)
    return {table: {column["name"] for column in inspector.get_columns(table)} for table in COLUMNS}


async def test_downgrade_drops_the_flags_and_upgrade_reads_an_earlier_post_as_having_none(
    db_engine, client, subscribed, post_with
):
    post_id = await post_with("Written before first replies.")
    await migrate(db_engine, lambda config: command.stamp(config, "head"))

    await migrate(db_engine, lambda config: command.downgrade(config, "0062"))
    async with db_engine.connect() as connection:
        columns = await connection.run_sync(_columns)
    assert all(not COLUMNS[table] & columns[table] for table in COLUMNS)

    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    async with db_engine.connect() as connection:
        columns = await connection.run_sync(_columns)
    assert all(COLUMNS[table] <= columns[table] for table in COLUMNS)
    read = (await client.get(f"{POSTS}/{post_id}")).json()
    assert read["text"]["first_reply"] is False
    assert read["versions"][0]["first_reply"] is False
