import pytest
import sqlalchemy as sa

from alembic import command
from tests.migrations import migrate


async def test_empty_eligibility_migration_can_be_reversed_without_changing_users(db_engine, user):
    await migrate(db_engine, lambda config: command.stamp(config, "0056"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0055"))
    await migrate(db_engine, lambda config: command.upgrade(config, "0056"))
    async with db_engine.connect() as connection:
        assert (
            await connection.scalar(
                sa.text("SELECT email FROM users WHERE id=:id"), {"id": user.id}
            )
            == user.email
        )
        columns = await connection.run_sync(
            lambda sync: {
                column["name"] for column in sa.inspect(sync).get_columns("trial_eligibility")
            }
        )
        assert columns == {"key_id", "fingerprint", "eligible"}
        foreign_keys = await connection.run_sync(
            lambda sync: sa.inspect(sync).get_foreign_keys("trial_eligibility")
        )
        assert foreign_keys == []


async def test_downgrade_cannot_erase_retained_trial_eligibility(db_engine):
    await migrate(db_engine, lambda config: command.stamp(config, "0056"))
    async with db_engine.begin() as connection:
        await connection.execute(
            sa.text(
                "INSERT INTO trial_eligibility (key_id,fingerprint,eligible) VALUES ('first',:fingerprint,false)"
            ),
            {"fingerprint": "a" * 64},
        )

    with pytest.raises(RuntimeError, match="Retained trial eligibility"):
        await migrate(db_engine, lambda config: command.downgrade(config, "0055"))

    async with db_engine.connect() as connection:
        assert await connection.scalar(sa.text("SELECT count(*) FROM trial_eligibility")) == 1
