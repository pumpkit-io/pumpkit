"""Migration 0037 makes unrevoked connections unique per User and app, and its downgrade doesn't."""

import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from tests.migrations import migrate

INDEX = "uq_app_connections_user_id_client_id_unrevoked"


async def _unique_indexes(db_engine) -> dict[str, list[str]]:
    def indexes(connection: Connection) -> dict[str, list[str]]:
        return {
            str(index["name"]): [str(column) for column in index["column_names"]]
            for index in sa.inspect(connection).get_indexes("app_connections")
            if index["unique"]
        }

    async with db_engine.connect() as connection:
        return await connection.run_sync(indexes)


async def test_upgrade_adds_the_unique_index_and_downgrade_drops_it(db_engine):
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0036"))
    assert INDEX not in await _unique_indexes(db_engine)

    await migrate(db_engine, lambda config: command.upgrade(config, "0037"))
    assert (await _unique_indexes(db_engine))[INDEX] == ["user_id", "client_id"]

    await migrate(db_engine, lambda config: command.downgrade(config, "0036"))
    assert INDEX not in await _unique_indexes(db_engine)
