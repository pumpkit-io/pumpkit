from sqlalchemy import inspect

from alembic import command
from tests.migrations import migrate


async def test_cardless_migration_can_upgrade_and_reverse_without_rewriting_billing(db_engine):
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0044"))
    async with db_engine.connect() as connection:
        before = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
    assert "free_access" not in before
    await migrate(db_engine, lambda config: command.upgrade(config, "0045"))
    async with db_engine.connect() as connection:
        after = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
    assert after == before | {
        "free_access",
        "coupon_claims",
        "coupon_history",
        "account_file_deletions",
    }
    await migrate(db_engine, lambda config: command.downgrade(config, "0044"))
