"""Migration 0068 adds the table Positioning drafts are kept in, and its downgrade drops it."""

import sqlalchemy as sa

from alembic import command
from tests.migrations import migrate
from tests.positioning.positioning import START_DRAFT, positioning_draft


async def _tables(db_engine) -> list[str]:
    async with db_engine.connect() as connection:
        return await connection.run_sync(lambda sync: sa.inspect(sync).get_table_names())


async def test_upgrade_adds_the_positioning_drafts_table_and_downgrade_drops_it(
    db_engine, client, subscribed
):
    await migrate(db_engine, lambda config: command.stamp(config, "head"))

    await migrate(db_engine, lambda config: command.downgrade(config, "0067"))
    assert "positioning_drafts" not in await _tables(db_engine)

    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    assert (await client.post(START_DRAFT)).status_code == 202
    assert (await positioning_draft(client))["state"] == "failed"
