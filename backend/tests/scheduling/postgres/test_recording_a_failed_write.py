"""
A write that fails records its attempt while a request holds the User and waits on the Post, as
discarding the Draft does. The attempt names its User, so recording it must lock the User first.
"""

import asyncio

import pytest
from sqlalchemy import select

from pumpkit.auth.models import User
from pumpkit.core.llm import LLMError
from pumpkit.posts.models import Post
from tests.billing.postgres.test_coupon_contention import wait_for_locks
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import HUMANIZED_POST, started_post_id

pytestmark = pytest.mark.postgres

POSTS = "/api/v1/posts"
BRIEFS = "/api/v1/briefs"


def _humanizer_fails_once_set(fake_llm) -> asyncio.Event:
    event = asyncio.Event()
    fake_llm.held[HUMANIZED_POST] = event
    fake_llm.standing[HUMANIZED_POST] = LLMError("provider down")
    return event


async def _fail_while_the_user_is_held(
    db_engine, db_session_maker, background_tasks, user, post_id, humanizing
):
    async with db_session_maker() as request:
        await request.scalar(select(User).where(User.id == user.id).with_for_update())
        humanizing.set()
        await wait_for_locks(db_engine, 1)
        await request.scalar(select(Post).where(Post.id == post_id).with_for_update())
        await request.commit()
    await asyncio.wait_for(background_tasks.wait(), 10)


async def test_a_failed_first_version_is_recorded_while_a_request_holds_the_user(
    client, subscribed, user, fake_llm, background_tasks, db_engine, db_session_maker
):
    await save_positioning(client)
    humanizing = _humanizer_fails_once_set(fake_llm)
    started = await client.post(BRIEFS, json={"brief": "ship small things"})
    post_id = started_post_id(started)

    await _fail_while_the_user_is_held(
        db_engine, db_session_maker, background_tasks, user, post_id, humanizing
    )

    post = (await client.get(f"{POSTS}/{post_id}")).json()
    assert post["writing_state"] == "not_written"


async def test_a_failed_feedback_is_recorded_while_a_request_holds_the_user(
    client, subscribed, user, fake_llm, background_tasks, db_engine, db_session_maker
):
    await save_positioning(client)
    fake_llm.replies.append({"post": "Version one.", "first_reply": None})
    started = await client.post(BRIEFS, json={"brief": "ship small things"})
    post_id = started_post_id(started)
    await background_tasks.wait()
    humanizing = _humanizer_fails_once_set(fake_llm)
    feedback = await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "shorter"})
    assert feedback.status_code == 202, feedback.text

    await _fail_while_the_user_is_held(
        db_engine, db_session_maker, background_tasks, user, post_id, humanizing
    )

    post = (await client.get(f"{POSTS}/{post_id}")).json()
    assert post["writing_state"] is None
    assert post["failed_feedback"]["feedback"] == "shorter"
