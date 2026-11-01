"""Migration 0036 creates the Connected apps tables, and its downgrade drops them."""

import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from tests.migrations import migrate

TABLES = {
    "oauth_clients",
    "app_connections",
    "oauth_authorizations",
    "oauth_refresh_tokens",
    "oauth_access_tokens",
}


async def _tables(db_engine) -> set[str]:
    def names(connection: Connection) -> set[str]:
        return set(sa.inspect(connection).get_table_names())

    async with db_engine.connect() as connection:
        return await connection.run_sync(names)


async def test_upgrade_creates_the_tables_and_downgrade_drops_them(db_engine):
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0035"))
    assert not TABLES & await _tables(db_engine)

    await migrate(db_engine, lambda config: command.upgrade(config, "0036"))
    assert TABLES <= await _tables(db_engine)

    await migrate(db_engine, lambda config: command.downgrade(config, "0035"))
    assert not TABLES & await _tables(db_engine)
