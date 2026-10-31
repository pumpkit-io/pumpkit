"""
Migration 0029 makes the Author directory from what Pumpkit already stored: an entry for every
listed or fetched handle, carrying the photo its fetch record held. Migration 0030 then seeds it.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from tests.migrations import insert, migrate

AUTHORS = "/api/v1/inspiration-authors"
DIRECTORY = "/api/v1/author-directory"
SEEDS = json.loads(
    (Path(__file__).parents[2] / "alembic" / "data" / "author_seeds.json").read_text()
)
PHOTO = "https://pbs.twimg.com/profile_images/1/levelsio_normal.jpg"
FETCHED_AT = datetime(2026, 10, 30, tzinfo=timezone.utc)


async def _down_to(db_engine, revision: str) -> None:
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, revision))


def _entries(connection: Connection) -> dict[str, tuple]:
    rows = connection.execute(
        sa.text("SELECT handle, name, photo_url, source FROM author_directory")
    )
    return {row.handle: (row.name, row.photo_url, row.source) for row in rows}


async def test_every_listed_or_fetched_handle_gets_an_entry_with_its_stored_photo(
    db_engine, user, client, subscribed
):
    await _down_to(db_engine, "0028")

    def store_before_the_directory(connection: Connection) -> None:
        insert(connection, "author_fetches", handle="levelsio", last_fetched_at=FETCHED_AT)
        connection.execute(
            sa.text("UPDATE author_fetches SET photo_url = :photo WHERE handle = 'levelsio'"),
            {"photo": PHOTO},
        )
        insert(connection, "author_fetches", handle="fetched_only", last_fetched_at=FETCHED_AT)
        for position, handle in enumerate(["levelsio", "never_fetched"]):
            insert(
                connection,
                "inspiration_authors",
                id=f"inspiration_author_{handle}",
                user_id=user.id,
                handle=handle,
                position=position,
                added_at=FETCHED_AT,
            )

    async with db_engine.begin() as connection:
        await connection.run_sync(store_before_the_directory)

    await migrate(db_engine, lambda config: command.upgrade(config, "0029"))

    async with db_engine.connect() as connection:
        assert await connection.run_sync(_entries) == {
            "levelsio": (None, PHOTO, "lookup"),
            "fetched_only": (None, None, "lookup"),
            "never_fetched": (None, None, "lookup"),
        }
    listed = (await client.get(AUTHORS)).json()["data"]
    assert [(author["handle"], author["photo_url"]) for author in listed] == [
        ("levelsio", PHOTO),
        ("never_fetched", None),
    ]


async def test_going_back_down_returns_the_photo_to_the_fetch_record(db_engine):
    await _down_to(db_engine, "0029")

    def store(connection: Connection) -> None:
        insert(connection, "author_fetches", handle="levelsio", last_fetched_at=FETCHED_AT)
        insert(
            connection,
            "author_directory",
            handle="levelsio",
            name="Pieter Levels",
            photo_url=PHOTO,
            added_at=FETCHED_AT,
            source="lookup",
        )

    async with db_engine.begin() as connection:
        await connection.run_sync(store)

    await migrate(db_engine, lambda config: command.downgrade(config, "0028"))

    def photos(connection: Connection) -> list:
        return list(connection.execute(sa.text("SELECT photo_url FROM author_fetches")).scalars())

    async with db_engine.connect() as connection:
        assert await connection.run_sync(photos) == [PHOTO]


async def test_the_seed_migration_inserts_every_seed_without_a_twitterapi_io_key(
    db_engine, client, subscribed, fake_x_reader, monkeypatch
):
    monkeypatch.delenv("TWITTERAPI_IO_API_KEY", raising=False)
    fake_x_reader.not_configured = True
    await _down_to(db_engine, "0029")

    await migrate(db_engine, lambda config: command.upgrade(config, "0030"))

    directory = (await client.get(DIRECTORY)).json()["data"]
    assert len(SEEDS) >= 150
    assert {entry["handle"]: (entry["name"], entry["photo_url"]) for entry in directory} == {
        seed["handle"]: (seed["name"], seed["photo_url"]) for seed in SEEDS
    }
    assert all(entry["persona_count"] == 0 for entry in directory)
    assert fake_x_reader.calls == fake_x_reader.profile_calls == []


async def test_the_seed_migration_skips_handles_already_in_the_directory(db_engine):
    seeded = SEEDS[0]["handle"]
    await _down_to(db_engine, "0029")

    def look_one_up(connection: Connection) -> None:
        insert(
            connection,
            "author_directory",
            handle=seeded,
            name="Looked up",
            photo_url=None,
            added_at=FETCHED_AT,
            source="lookup",
        )

    async with db_engine.begin() as connection:
        await connection.run_sync(look_one_up)

    await migrate(db_engine, lambda config: command.upgrade(config, "0030"))

    async with db_engine.connect() as connection:
        entries = await connection.run_sync(_entries)
    assert entries[seeded] == ("Looked up", None, "lookup")
    assert len(entries) == len(SEEDS)
    assert {source for _, _, source in entries.values()} == {"seed", "lookup"}
