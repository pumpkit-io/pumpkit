"""Migration 0039 drops the API keys and their table, and its downgrade recreates the table empty."""

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from tests.migrations import insert, migrate


async def _tables(db_engine) -> set[str]:
    def tables(connection: Connection) -> set[str]:
        return set(sa.inspect(connection).get_table_names())

    async with db_engine.connect() as connection:
        return await connection.run_sync(tables)


async def test_upgrade_drops_api_keys_and_downgrade_recreates_the_table_empty(db_engine, user):
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0038"))
    assert "api_keys" in await _tables(db_engine)

    async with db_engine.begin() as connection:
        await connection.run_sync(
            lambda sync: insert(
                sync,
                "api_keys",
                id="api_key_old",
                user_id=user.id,
                name="Work laptop",
                key_hash="hash",
                prefix="pumpkit_abcdefgh",
                created_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
            )
        )

    await migrate(db_engine, lambda config: command.upgrade(config, "0039"))
    assert "api_keys" not in await _tables(db_engine)

    await migrate(db_engine, lambda config: command.downgrade(config, "0038"))
    async with db_engine.connect() as connection:
        count = await connection.scalar(sa.text("SELECT count(*) FROM api_keys"))
    assert count == 0


@pytest.fixture
async def user(legacy_user):
    return legacy_user
