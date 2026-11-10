"""Migration 0040 turns a cancellation at period end into its date, and its downgrade back."""

from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from alembic import command
from tests.migrations import insert, migrate

PERIOD_END = datetime(2026, 11, 9, tzinfo=timezone.utc)


def _subscription(sub_id: str, user_id: str, *, cancel_at_period_end: bool) -> dict:
    return dict(
        id=sub_id,
        user_id=user_id,
        stripe_subscription_id=f"stripe_{sub_id}",
        stripe_customer_id="cus_1",
        status="trialing",
        current_period_end=PERIOD_END,
        cancel_at_period_end=cancel_at_period_end,
        stripe_created_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
    )


async def _column(db_engine, column: str) -> dict[str, object]:
    async with db_engine.connect() as connection:
        rows = await connection.execute(
            sa.text(f"SELECT id, {column} FROM subscriptions ORDER BY id")
        )
        return {row[0]: row[1] for row in rows}


async def test_upgrade_dates_a_cancellation_at_period_end_and_downgrade_restores_the_flag(
    db_engine, user
):
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0039"))
    async with db_engine.begin() as connection:
        for sub_id, cancelled in (("sub_cancelled", True), ("sub_renewing", False)):
            values = _subscription(sub_id, user.id, cancel_at_period_end=cancelled)
            await connection.run_sync(lambda sync, v=values: insert(sync, "subscriptions", **v))

    await migrate(db_engine, lambda config: command.upgrade(config, "0040"))
    cancel_at = await _column(db_engine, "cancel_at")
    assert cancel_at["sub_renewing"] is None
    # SQLite drops the time zone that Postgres keeps.
    assert str(cancel_at["sub_cancelled"]).startswith("2026-11-09 00:00:00")

    await migrate(db_engine, lambda config: command.downgrade(config, "0039"))
    assert await _column(db_engine, "cancel_at_period_end") == {
        "sub_cancelled": 1,
        "sub_renewing": 0,
    }


@pytest.fixture
async def user(legacy_user):
    return legacy_user
