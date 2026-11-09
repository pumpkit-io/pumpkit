import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from alembic import command
from tests.migrations import migrate


async def test_stable_x_identity_and_shared_contact_email_can_be_migrated_and_reversed(
    db_engine, user
):
    await migrate(db_engine, lambda config: command.stamp(config, "0055"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0054"))
    async with db_engine.connect() as connection:
        columns = await connection.run_sync(
            lambda sync: {c["name"] for c in sa.inspect(sync).get_columns("users")}
        )
        assert "x_user_id" not in columns
    await migrate(db_engine, lambda config: command.upgrade(config, "0055"))
    async with db_engine.begin() as connection:
        await connection.execute(
            sa.text("UPDATE users SET x_user_id='1001', x_handle='ada' WHERE id=:id"),
            {"id": user.id},
        )
        await connection.execute(
            sa.text(
                "INSERT INTO users (id,email,display_name,is_admin,x_user_id,x_handle) VALUES ('user_other',:email,'Other',false,'2002','other')"
            ),
            {"email": user.email},
        )
    async with db_engine.begin() as connection:
        with pytest.raises(IntegrityError):
            async with connection.begin_nested():
                await connection.execute(
                    sa.text("UPDATE users SET x_user_id='1001' WHERE id='user_other'")
                )
    with pytest.raises(RuntimeError, match="unique contact emails"):
        await migrate(db_engine, lambda config: command.downgrade(config, "0054"))
    async with db_engine.begin() as connection:
        await connection.execute(sa.text("DELETE FROM users WHERE id='user_other'"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0054"))
    async with db_engine.connect() as connection:
        preserved = await connection.scalar(
            sa.text("SELECT email FROM users WHERE id=:id"), {"id": user.id}
        )
        assert preserved == user.email
