"""Migration 0038 adds when an app's cached metadata document goes stale, and its downgrade drops it."""

import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from tests.migrations import migrate


async def _columns(db_engine) -> set[str]:
    def columns(connection: Connection) -> set[str]:
        return {
            str(column["name"]) for column in sa.inspect(connection).get_columns("oauth_clients")
        }

    async with db_engine.connect() as connection:
        return await connection.run_sync(columns)


async def test_upgrade_adds_metadata_expires_at_and_downgrade_drops_it(db_engine):
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0037"))
    assert "metadata_expires_at" not in await _columns(db_engine)

    await migrate(db_engine, lambda config: command.upgrade(config, "0038"))
    assert "metadata_expires_at" in await _columns(db_engine)

    await migrate(db_engine, lambda config: command.downgrade(config, "0037"))
    assert "metadata_expires_at" not in await _columns(db_engine)
