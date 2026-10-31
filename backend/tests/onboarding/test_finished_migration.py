"""Migration 0035 counts every User who already has an X connection and an author as finished."""

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from pumpkit.auth.models import User
from tests.migrations import insert, migrate

ONBOARDING = "/api/v1/onboarding"
AT = datetime(2026, 10, 30, tzinfo=timezone.utc)


def _connect_x(connection: Connection, user_id: str) -> None:
    insert(
        connection,
        "x_connections",
        id=f"x_connection_{user_id}",
        user_id=user_id,
        x_user_id=f"x_{user_id}",
        handle=f"handle_{user_id}",
        access_token_encrypted="",
        refresh_token_encrypted="",
        access_token_expires_at=AT,
        scopes="tweet.write",
        needs_reconnect=False,
        created_at=AT,
        updated_at=AT,
    )


def _add_author(connection: Connection, user_id: str) -> None:
    insert(
        connection,
        "inspiration_authors",
        id=f"inspiration_author_{user_id}",
        user_id=user_id,
        handle="levelsio",
        position=0,
        added_at=AT,
    )


async def _new_user(db, email: str) -> str:
    other = User(email=email, display_name=email)
    db.add(other)
    await db.commit()
    return other.id


async def test_only_users_with_both_an_x_connection_and_an_author_count_as_finished(
    db_engine, db, user, client, subscribed
):
    x_only = await _new_user(db, "x-only@example.com")
    author_only = await _new_user(db, "author-only@example.com")
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0034"))

    def store_before_onboarding(connection: Connection) -> None:
        _connect_x(connection, user.id)
        _add_author(connection, user.id)
        _connect_x(connection, x_only)
        _add_author(connection, author_only)

    async with db_engine.begin() as connection:
        await connection.run_sync(store_before_onboarding)

    await migrate(db_engine, lambda config: command.upgrade(config, "0035"))

    def finished(connection: Connection) -> set[str]:
        return set(connection.execute(sa.text("SELECT user_id FROM onboarding_finishes")).scalars())

    async with db_engine.connect() as connection:
        assert await connection.run_sync(finished) == {user.id}
    assert (await client.get(ONBOARDING)).json() == {"next_step": None}
