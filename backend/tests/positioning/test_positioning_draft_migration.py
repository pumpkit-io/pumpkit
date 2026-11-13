"""Migration 0059 adds what a Positioning draft reads and what limits it; its downgrade drops both."""

import sqlalchemy as sa

from alembic import command
from tests.migrations import migrate
from tests.positioning.positioning import DRAFT, DRAFTED


async def _schema(db_engine) -> tuple[list[str], list[str]]:
    def read(sync):
        inspector = sa.inspect(sync)
        columns = [column["name"] for column in inspector.get_columns("x_connections")]
        return inspector.get_table_names(), columns

    async with db_engine.connect() as connection:
        return await connection.run_sync(read)


async def test_upgrade_adds_the_profile_columns_and_the_draft_requests_and_downgrade_drops_them(
    db_engine, client, subscribed, fake_llm, fake_x_reader, connect_x
):
    await migrate(db_engine, lambda config: command.stamp(config, "head"))

    await migrate(db_engine, lambda config: command.downgrade(config, "0058"))
    tables, columns = await _schema(db_engine)
    assert "positioning_draft_requests" not in tables
    assert not {"bio", "location", "website"} & set(columns)

    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    await connect_x()
    fake_x_reader.posts["ada"] = []
    fake_llm.replies = [{"positioning": DRAFTED}]
    drafted = await client.post(DRAFT)
    assert drafted.status_code == 200
