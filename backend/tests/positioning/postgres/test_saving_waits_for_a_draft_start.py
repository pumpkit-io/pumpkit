"""
Saving a Positioning locks the User as a draft's start does, so a save can't land between the
start's check for a Positioning and the draft it starts.
"""

import asyncio

import pytest
from sqlalchemy import select, text

from pumpkit.auth.models import User
from tests.positioning.positioning import POSITIONING, TEXT, save_positioning

pytestmark = pytest.mark.postgres


async def _waiting_on_locks(engine, count: int) -> None:
    for _ in range(200):
        async with engine.connect() as connection:
            waiting = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name = "
                    "current_setting('application_name') AND wait_event_type = 'Lock'"
                )
            )
        if waiting >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("The save did not wait on the User's lock")


async def test_a_save_on_the_web_and_over_mcp_waits_for_the_users_lock(
    client, subscribed, mcp, user, db_engine, db_session_maker
):
    # A first save's insert already waits on the User's row for its foreign key; a later one doesn't.
    await save_positioning(client)
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        web = asyncio.create_task(client.put(POSITIONING, json={"text": TEXT}))
        tool = asyncio.create_task(mcp.call_tool("set_positioning", text=TEXT))
        try:
            await _waiting_on_locks(db_engine, 2)
        finally:
            await control.commit()
        saved, called = await asyncio.wait_for(asyncio.gather(web, tool), 10)

    assert saved.status_code == 200
    assert called["isError"] is False
