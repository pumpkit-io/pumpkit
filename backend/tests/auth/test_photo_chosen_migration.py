"""
Migration 0025 adds the Photo chosen marker, set for every existing User who has a Photo, so
Pumpkit never replaces a Photo a User had before the marker existed.
"""

import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from tests.migrations import insert, migrate

PHOTO = "data:image/jpeg;base64,UGhvdG8="


async def test_users_with_a_photo_get_the_marker_and_users_without_one_do_not(db_engine, user):
    await migrate(db_engine, lambda config: command.stamp(config, "0025"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0024"))

    def add_user_with_a_photo(connection: Connection) -> None:
        insert(
            connection,
            "users",
            id="user_with_photo",
            email="bob@example.com",
            display_name="bob",
            avatar_data_url=PHOTO,
            is_admin=False,
        )

    async with db_engine.begin() as connection:
        await connection.run_sync(add_user_with_a_photo)

    await migrate(db_engine, lambda config: command.upgrade(config, "0025"))

    def markers(connection: Connection) -> dict[str, bool]:
        rows = connection.execute(sa.text("SELECT id, photo_chosen_at FROM users"))
        return {row.id: row.photo_chosen_at is not None for row in rows}

    async with db_engine.connect() as connection:
        assert await connection.run_sync(markers) == {user.id: False, "user_with_photo": True}
