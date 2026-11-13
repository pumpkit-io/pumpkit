"""Migration 0058 adds the table Positionings are stored in, and its downgrade drops it."""

import sqlalchemy as sa

from alembic import command
from tests.migrations import migrate

POSITIONING = "/api/v1/positioning"


async def _tables(db_engine) -> list[str]:
    async with db_engine.connect() as connection:
        return await connection.run_sync(lambda sync: sa.inspect(sync).get_table_names())


async def test_upgrade_adds_the_positionings_table_and_downgrade_drops_it(
    db_engine, client, subscribed
):
    await migrate(db_engine, lambda config: command.stamp(config, "head"))

    await migrate(db_engine, lambda config: command.downgrade(config, "0057"))
    assert "positionings" not in await _tables(db_engine)

    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    saved = await client.put(POSITIONING, json={"text": "I post about bootstrapping."})
    assert saved.status_code == 200
    assert (await client.get(POSITIONING)).json() == saved.json()
