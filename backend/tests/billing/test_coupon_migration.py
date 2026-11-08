from sqlalchemy import inspect

from alembic import command
from tests.migrations import migrate


async def test_coupon_migration_preserves_existing_tables_and_can_be_reversed(db_engine):
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0043"))
    async with db_engine.connect() as connection:
        before = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
    assert "coupons" not in before
    assert {"subscriptions", "top_ups", "users"} <= before

    await migrate(db_engine, lambda config: command.upgrade(config, "0044"))
    async with db_engine.connect() as connection:
        upgraded = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
    assert upgraded == before | {"coupons"}

    await migrate(db_engine, lambda config: command.downgrade(config, "0043"))
    async with db_engine.connect() as connection:
        after = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
    assert after == before
