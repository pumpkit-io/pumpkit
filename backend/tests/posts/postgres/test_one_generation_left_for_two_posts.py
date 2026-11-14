"""
Two requests on different Posts with one Generation left: Retry and Feedback lock the User before
the Post, so the second request counts the first one's write and is refused.
"""

import asyncio

import pytest
from sqlalchemy import select, text

from pumpkit.auth.models import User
from pumpkit.core.config import settings
from pumpkit.core.llm import LLMError
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import HUMANIZED_POST, started_post_id

pytestmark = pytest.mark.postgres

BRIEFS = "/api/v1/briefs"
POSTS = "/api/v1/posts"


@pytest.fixture
async def ready(client, subscribed, monkeypatch):
    await save_positioning(client)
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 2)


async def _post(client, fake_llm, background_tasks, *, written: bool) -> str:
    """A Post whose first Version was written, or failed and waits for Retry."""
    fake_llm.standing[HUMANIZED_POST] = (
        {"post": "Written.", "first_reply": None} if written else LLMError("provider down")
    )
    post_id = started_post_id(await client.post(BRIEFS, json={"brief": "ship small things"}))
    await background_tasks.wait()
    return post_id


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
    raise AssertionError("The requests did not wait on the User's lock")


async def _both_after_the_users_lock(db_engine, db_session_maker, user, *requests) -> list[int]:
    """Starts `requests` while the User is locked, so neither can pass the other, then frees it."""
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        tasks = [asyncio.create_task(request) for request in requests]
        try:
            await _waiting_on_locks(db_engine, len(tasks))
        finally:
            await control.commit()
        responses = await asyncio.wait_for(asyncio.gather(*tasks), 10)
    return sorted(response.status_code for response in responses)


@pytest.mark.parametrize("second", ["retry", "feedback"])
async def test_one_generation_left_starts_one_of_two_writes_on_different_posts(
    client, ready, user, fake_llm, background_tasks, db_engine, db_session_maker, second
):
    written = await _post(client, fake_llm, background_tasks, written=True)
    failed = await _post(client, fake_llm, background_tasks, written=False)
    other = (
        await _post(client, fake_llm, background_tasks, written=False)
        if second == "retry"
        else written
    )
    second_request = (
        client.post(f"{POSTS}/{other}/retry")
        if second == "retry"
        else client.post(f"{POSTS}/{other}/versions", json={"feedback": "shorter"})
    )

    statuses = await _both_after_the_users_lock(
        db_engine, db_session_maker, user, client.post(f"{POSTS}/{failed}/retry"), second_request
    )

    assert statuses == [202, 409]
