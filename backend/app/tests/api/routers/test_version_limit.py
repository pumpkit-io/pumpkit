from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.llm import LLMError
from app.core.x_reader import FetchedPost
from app.db.models import Post, Subscription, User, VersionAttempt
from app.db.session import get_async_db
from app.main import app

AUTHORS = "/api/v1/inspiration-authors"
POSTS = "/api/v1/posts"


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


@pytest.fixture
async def with_author(client, subscribed, fake_x_reader):
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201


async def _store_attempts(db, user_id: str, times: list[datetime], status: str = "succeeded"):
    """One Post of `user_id` with an attempt made at each of `times`."""
    post = Post(user_id=user_id, brief="earlier", corpus_post_ids=[], created_at=times[0])
    db.add(post)
    await db.flush()
    for sequence, moment in enumerate(times, start=1):
        db.add(
            VersionAttempt(
                post_id=post.id,
                sequence=sequence,
                status=status,
                error="LLMError: down" if status == "failed" else None,
                created_at=moment,
            )
        )
    await db.commit()


async def test_the_31st_post_within_an_hour_returns_429_with_when_to_retry_and_no_model_call(
    client, db, user, with_author, fake_llm, clock
):
    first = clock()
    await _store_attempts(db, user.id, [first + timedelta(minutes=n) for n in range(30)])
    clock.advance(timedelta(minutes=40))

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 429
    assert response.json() == {
        "detail": "You've made 30 attempts at a Version in the last hour.",
        "retry_at": _iso(first + timedelta(hours=1)),
    }
    assert response.headers["Retry-After"] == str(20 * 60)
    assert fake_llm.calls == []


async def test_an_attempt_stops_counting_exactly_an_hour_after_it_was_made(
    client, db, user, with_author, fake_llm, clock
):
    first = clock()
    await _store_attempts(db, user.id, [first + timedelta(minutes=n) for n in range(30)])
    clock.advance(timedelta(hours=1))
    fake_llm.replies = [{"post": "draft"}, {"post": "final"}]

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 201


async def test_a_second_before_the_oldest_attempt_ages_out_the_limit_still_holds(
    client, db, user, with_author, fake_llm, clock
):
    first = clock()
    await _store_attempts(db, user.id, [first + timedelta(minutes=n) for n in range(30)])
    clock.advance(timedelta(minutes=59, seconds=59))

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    assert fake_llm.calls == []


async def test_failed_attempts_count_toward_the_limit(
    client, db, user, with_author, fake_llm, clock
):
    first = clock()
    await _store_attempts(db, user.id, [first + timedelta(minutes=n) for n in range(29)])
    fake_llm.replies = [LLMError("provider down")]
    assert (await client.post(POSTS, json={"brief": "ship"})).status_code == 502
    fake_llm.calls.clear()

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 429
    assert fake_llm.calls == []


async def test_the_31st_attempt_giving_feedback_returns_429_with_no_model_call(
    client, db, user, with_author, fake_llm, clock
):
    fake_llm.replies = [{"post": "draft"}, {"post": "final"}]
    post_id = (await client.post(POSTS, json={"brief": "ship"})).json()["id"]
    first = clock()
    await _store_attempts(
        db, user.id, [first + timedelta(minutes=n) for n in range(29)], status="failed"
    )
    fake_llm.calls.clear()
    clock.advance(timedelta(minutes=30))

    response = await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "shorter"})

    assert response.status_code == 429
    assert response.json()["retry_at"] == _iso(first + timedelta(hours=1))
    assert fake_llm.calls == []


async def test_attempts_past_the_limit_from_concurrent_requests_push_the_retry_time_back(
    client, db, user, with_author, fake_llm, clock
):
    first = clock()
    await _store_attempts(db, user.id, [first + timedelta(minutes=n) for n in range(32)])
    clock.advance(timedelta(minutes=40))

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.json()["retry_at"] == _iso(first + timedelta(hours=1, minutes=2))


async def _sign_in_as_another_subscribed_user(db) -> None:
    other = User(email="bob@example.com", display_name="Bob")
    db.add(other)
    await db.flush()
    db.add(
        Subscription(
            user_id=other.id,
            stripe_subscription_id="sub_bob",
            stripe_customer_id="cus_bob",
            status="active",
            stripe_created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    )
    await db.commit()
    other_id = other.id

    async def _other(request_db: AsyncSession = Depends(get_async_db)) -> User:
        loaded = await request_db.get(User, other_id)
        assert loaded is not None
        return loaded

    app.dependency_overrides[get_current_user] = _other


async def test_the_limit_is_per_user_so_another_users_attempts_dont_count(
    client, db, user, with_author, fake_llm, clock
):
    await _store_attempts(db, user.id, [clock() + timedelta(minutes=n) for n in range(30)])
    await _sign_in_as_another_subscribed_user(db)
    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201
    fake_llm.replies = [{"post": "draft"}, {"post": "final"}]

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 201
