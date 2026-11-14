"""
Migration 0061 adds how a Brief was planned and each Idea's Plan (ADR 0025); its downgrade
drops them with the types they brought.
"""

import sqlalchemy as sa
from sqlalchemy import Connection

from alembic import command
from tests.migrations import migrate
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import PLAN, started_post_id

POSTS = "/api/v1/posts"
BRIEFS = "/api/v1/briefs"
PLAN_COLUMNS = {
    "whole_brief",
    "core_idea",
    "takeaway",
    "plan_reasoning",
    "funnel",
    "desired_action",
    "format",
    "length",
    "structure",
}
PLANNING_COLUMNS = {"positioning", "planning_reasoning", "planning_model", "planning_usage"}
NEW_TYPES = {"funnel_enum", "desired_action_enum", "length_enum", "structure_enum"}


def _columns(connection: Connection) -> tuple[set[str], set[str]]:
    inspector = sa.inspect(connection)
    return (
        {column["name"] for column in inspector.get_columns("briefs")},
        {column["name"] for column in inspector.get_columns("ideas")},
    )


def _enum_types(connection: Connection) -> set[str]:
    """The enum types of the schema under test; SQLite has none."""
    if connection.dialect.name != "postgresql":
        return set()
    names = connection.execute(
        sa.text(
            "SELECT typname FROM pg_type JOIN pg_namespace ON pg_namespace.oid = typnamespace "
            "WHERE typtype = 'e' AND nspname = current_schema()"
        )
    )
    return set(names.scalars())


async def test_downgrade_drops_the_plan_and_upgrade_leaves_an_earlier_post_without_one(
    db_engine, client, subscribed, post_with
):
    post_id = await post_with("Written before plans.")
    await migrate(db_engine, lambda config: command.stamp(config, "head"))

    await migrate(db_engine, lambda config: command.downgrade(config, "0060"))
    async with db_engine.connect() as connection:
        briefs, ideas = await connection.run_sync(_columns)
        types = await connection.run_sync(_enum_types)
    assert not PLANNING_COLUMNS & briefs
    assert not PLAN_COLUMNS & ideas
    assert not NEW_TYPES & types

    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    async with db_engine.connect() as connection:
        briefs, ideas = await connection.run_sync(_columns)
        whole = (await connection.execute(sa.text("SELECT whole_brief FROM ideas"))).scalars()
        assert [bool(value) for value in whole] == [True]
    assert PLANNING_COLUMNS <= briefs
    assert PLAN_COLUMNS <= ideas
    read = await client.get(f"{POSTS}/{post_id}")
    assert read.status_code == 200
    assert read.json()["plan"] is None


async def test_a_post_started_after_the_upgrade_is_read_back_with_its_plan(
    db_engine, client, subscribed, fake_x_reader, fake_llm
):
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0060"))
    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    await save_positioning(client)
    fake_llm.replies = [{"post": "the final"}]

    started = await client.post(BRIEFS, json={"brief": "ship small things"})

    assert started.status_code == 201
    read = await client.get(f"{POSTS}/{started_post_id(started)}")
    assert read.json()["plan"] == PLAN
