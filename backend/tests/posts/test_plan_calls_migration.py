"""Migration 0065 adds the table plan calls are counted in, and its downgrade drops it."""

import sqlalchemy as sa

from alembic import command
from tests.migrations import migrate
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import started_post_id


async def _tables(db_engine) -> list[str]:
    async with db_engine.connect() as connection:
        return await connection.run_sync(lambda sync: sa.inspect(sync).get_table_names())


async def test_upgrade_adds_the_plan_calls_table_and_downgrade_drops_it(
    db_engine, client, subscribed, fake_llm
):
    await migrate(db_engine, lambda config: command.stamp(config, "head"))

    await migrate(db_engine, lambda config: command.downgrade(config, "0064"))
    assert "plan_calls" not in await _tables(db_engine)

    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    await save_positioning(client)
    fake_llm.replies = [{"post": "the final"}]
    planned = await client.post("/api/v1/briefs", json={"brief": "ship small things"})
    assert started_post_id(planned).startswith("post_")
