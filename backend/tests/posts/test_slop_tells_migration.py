"""
Migration 0024 drops the slop check's tells from Version attempts, since the check no longer runs.
"""

import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from tests.migrations import migrate

POSTS = "/api/v1/posts"


def _columns(connection: Connection) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns("version_attempts")}


async def test_the_migration_runs_down_and_up_again(db_engine, post_with, client):
    post_id = await post_with("One.")
    await migrate(db_engine, lambda config: command.stamp(config, "0024"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0023"))

    def tells(connection: Connection) -> list:
        return list(
            connection.execute(sa.text("SELECT slop_tells FROM version_attempts")).scalars()
        )

    # The code before 0024 reads every succeeded attempt's tells as a list.
    async with db_engine.connect() as connection:
        assert await connection.run_sync(tells) == ["[]"]

    await migrate(db_engine, lambda config: command.upgrade(config, "0024"))
    async with db_engine.connect() as connection:
        assert "slop_tells" not in await connection.run_sync(_columns)
    read = (await client.get(f"{POSTS}/{post_id}")).json()
    assert read["versions"][0]["parts"][0]["text"] == "One."
