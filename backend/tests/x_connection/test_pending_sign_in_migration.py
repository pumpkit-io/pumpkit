from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from tests.migrations import insert, migrate


async def test_pending_sign_ins_expand_and_contract_without_changing_legacy_authorizations(
    db_engine, user
):
    await migrate(db_engine, lambda config: command.stamp(config, "0054"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0053"))
    now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)

    def legacy_authorization(connection: Connection) -> None:
        insert(
            connection,
            "pending_x_authorizations",
            state_hash="legacy-state-hash",
            user_id=user.id,
            code_verifier_encrypted="legacy-encrypted-verifier",
            created_at=now,
            expires_at=now + timedelta(minutes=10),
        )

    async with db_engine.begin() as connection:
        await connection.run_sync(legacy_authorization)

    await migrate(db_engine, lambda config: command.upgrade(config, "0054"))

    def unauthenticated_attempt(connection: Connection) -> None:
        insert(
            connection,
            "pending_x_sign_ins",
            state_hash="sign-in-state-hash",
            browser_secret_hash="browser-secret-hash",
            code_verifier_encrypted="sign-in-encrypted-verifier",
            return_to="/oauth/consent?request=request_one",
            created_at=now,
            expires_at=now + timedelta(minutes=10),
        )
        assert sa.inspect(connection).get_foreign_keys("pending_x_sign_ins") == []

    async with db_engine.begin() as connection:
        await connection.run_sync(unauthenticated_attempt)

    await migrate(db_engine, lambda config: command.downgrade(config, "0053"))

    async with db_engine.connect() as connection:
        preserved = await connection.execute(
            sa.text("SELECT user_id, code_verifier_encrypted FROM pending_x_authorizations")
        )
        assert preserved.one() == (user.id, "legacy-encrypted-verifier")
        assert not await connection.run_sync(
            lambda sync: sa.inspect(sync).has_table("pending_x_sign_ins")
        )


@pytest.fixture
async def user(legacy_user):
    return legacy_user
