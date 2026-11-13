"""Migration 0062 adds what a Version keeps of its sketches and merge; its downgrade drops it."""

import sqlalchemy as sa
from sqlalchemy import Connection, select

from alembic import command
from pumpkit.posts.models import VersionAttempt
from tests.migrations import migrate
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import MERGED_SKETCH, merged

POSTS = "/api/v1/posts"
COLUMNS = {"hook_levers", "hook_types", "cta_type", "sketches", "merge"}


def _columns(connection: Connection) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns("version_attempts")}


async def test_downgrade_drops_the_columns_and_upgrade_leaves_an_earlier_version_without_them(
    db_engine, client, subscribed, post_with
):
    post_id = await post_with("Written before sketches.")
    await migrate(db_engine, lambda config: command.stamp(config, "head"))

    await migrate(db_engine, lambda config: command.downgrade(config, "0061"))
    async with db_engine.connect() as connection:
        assert not COLUMNS & await connection.run_sync(_columns)

    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    async with db_engine.connect() as connection:
        assert COLUMNS <= await connection.run_sync(_columns)
    read = await client.get(f"{POSTS}/{post_id}")
    assert read.status_code == 200
    assert [part["text"] for part in read.json()["text"]["parts"]] == ["Written before sketches."]


async def test_a_single_post_written_after_the_upgrade_keeps_its_sketches(
    db_engine, db, client, subscribed, fake_llm
):
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0061"))
    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    await save_positioning(client)
    fake_llm.standing[MERGED_SKETCH] = merged(hook_types=["story"], reasoning="Sketch 2's story.")
    fake_llm.replies = [{"post": "The final.", "first_reply": None}]

    started = await client.post(POSTS, json={"brief": "ship small things"})

    assert started.status_code == 201, started.text
    [version] = (await db.scalars(select(VersionAttempt))).all()
    assert version.sketches is not None and len(version.sketches) == 5
    assert version.merge is not None and version.merge["reasoning"] == "Sketch 2's story."
    assert version.hook_types == ["story"]
