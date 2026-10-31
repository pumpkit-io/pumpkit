from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, TypeVar

import pytest

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.billing.models import Subscription
from pumpkit.core.config import settings
from pumpkit.main import app
from pumpkit.posts.llm import FakeLLM, StructuredResult, get_llm
from pumpkit.posts.models import Post, VersionAttempt
from tests.posts.writing_replies import written

AUTHORS = "/api/v1/inspiration-authors"
POSTS = "/api/v1/posts"
SETTINGS_URL = "http://localhost:5173/settings"

T = TypeVar("T")


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
async def with_author(client, subscribed, fake_x_reader):
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(post_id="levelsio-0", text="levelsio post", posted_at=_utc(2026, 9, 1))
    ]
    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201


@pytest.fixture
def cap(monkeypatch):
    def _cap(value: Optional[int]) -> None:
        monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", value)

    return _cap


async def _subscription(db, subscription: Subscription, **fields: Any) -> None:
    for name, value in fields.items():
        setattr(subscription, name, value)
    db.add(subscription)
    await db.commit()


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
                version_number=sequence if status == "succeeded" else None,
                format="post",
                status=status,
                parts=["earlier"] if status == "succeeded" else None,
                error="LLMError: down" if status == "failed" else None,
                created_at=moment,
            )
        )
    await db.commit()


def _times(start: datetime, count: int) -> list[datetime]:
    return [start + timedelta(minutes=n) for n in range(count)]


async def test_starting_a_post_with_no_generations_left_is_refused_with_the_reset_date(
    client, db, user, subscribed, with_author, fake_llm, fixed_clock
):
    await _subscription(db, subscribed, billing_cycle_anchor=_utc(2026, 9, 14, 9))
    await _store_attempts(db, user.id, _times(_utc(2026, 9, 20), 500))

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "You've used this period's 500 generations. They reset on 14 October. "
            "Failed attempts don't count."
        ),
        "url": SETTINGS_URL,
        "code": "ALLOWANCE_USED_UP",
        "ran_out": "generations",
        "needed": 1,
        "left": 0,
        "resets_at": _iso(_utc(2026, 10, 14, 9)),
        "way_out": None,
    }
    assert fake_llm.calls == []


async def test_versions_written_before_the_period_started_dont_count(
    client, db, user, subscribed, with_author, fake_llm, fixed_clock, cap
):
    cap(3)
    await _subscription(db, subscribed, billing_cycle_anchor=_utc(2026, 9, 14, 9))
    await _store_attempts(db, user.id, _times(_utc(2026, 9, 14, 8), 10))
    await _store_attempts(db, user.id, _times(_utc(2026, 9, 14, 9), 2))
    fake_llm.replies = [written("sketch"), {"post": "final"}]

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 201


async def test_failed_attempts_dont_use_a_generation(
    client, db, user, subscribed, with_author, fake_llm, fixed_clock, cap
):
    cap(3)
    await _store_attempts(db, user.id, _times(_utc(2026, 10, 2), 2))
    await _store_attempts(db, user.id, _times(_utc(2026, 10, 3), 10), status="failed")
    fake_llm.replies = [written("sketch"), {"post": "final"}]

    assert (await client.post(POSTS, json={"brief": "ship"})).status_code == 201
    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 409
    assert response.json()["left"] == 0


async def test_without_an_anchor_synced_periods_start_on_the_subscriptions_start(
    client, db, user, subscribed, with_author, fake_llm, fixed_clock, cap
):
    # The `subscribed` fixture started on 1 October.
    cap(1)
    await _store_attempts(db, user.id, [_utc(2026, 10, 1, 0, 1)])

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.json()["resets_at"] == _iso(_utc(2026, 11, 1))


@pytest.mark.parametrize(
    ("now", "reset"),
    [
        (_utc(2026, 11, 30, 12), _utc(2026, 12, 31, 10)),
        (_utc(2027, 2, 28, 12), _utc(2027, 3, 31, 10)),
        (_utc(2028, 2, 29, 12), _utc(2028, 3, 31, 10)),
    ],
)
async def test_an_anchor_on_the_31st_resets_on_the_last_day_of_a_shorter_month(
    client, db, user, subscribed, with_author, fake_llm, fixed_clock, cap, now, reset
):
    cap(1)
    await _subscription(db, subscribed, billing_cycle_anchor=_utc(2026, 1, 31, 10))
    period_start = now.replace(hour=10)
    await _store_attempts(db, user.id, [period_start - timedelta(minutes=1)])
    await _store_attempts(db, user.id, [period_start])
    fixed_clock._now = now

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 409
    assert response.json()["resets_at"] == _iso(reset)


async def test_an_annual_plan_resets_every_month(
    client, db, user, subscribed, with_author, fake_llm, fixed_clock, cap
):
    cap(1)
    await _subscription(
        db,
        subscribed,
        plan_key="pumpkit_pro_annual",
        billing_cycle_anchor=_utc(2026, 1, 14, 9),
        current_period_end=_utc(2027, 1, 14, 9),
    )
    await _store_attempts(db, user.id, [_utc(2026, 9, 14, 8, 59)])
    fake_llm.replies = [written("sketch"), {"post": "final"}]

    assert (await client.post(POSTS, json={"brief": "ship"})).status_code == 201
    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.json()["resets_at"] == _iso(_utc(2026, 10, 14, 9))


async def test_a_trial_gets_a_quarter_of_the_generations_for_the_whole_trial(
    client, db, user, subscribed, with_author, fake_llm, fixed_clock
):
    await _subscription(
        db,
        subscribed,
        status="trialing",
        trial_start=_utc(2026, 10, 7, 9),
        trial_end=_utc(2026, 10, 14, 9),
        billing_cycle_anchor=_utc(2026, 10, 14, 9),
    )
    await _store_attempts(db, user.id, _times(_utc(2026, 10, 7, 9), 124))
    fake_llm.replies = [written("sketch"), {"post": "final"}]

    assert (await client.post(POSTS, json={"brief": "ship"})).status_code == 201
    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == (
        "You've used your trial's 125 generations. Your trial ends on 14 October. "
        "Failed attempts don't count."
    )
    assert body["resets_at"] == _iso(_utc(2026, 10, 14, 9))
    assert body["way_out"] == "subscribe_now"


async def test_the_trial_share_of_a_cap_is_rounded_down(
    client, db, user, subscribed, with_author, fake_llm, fixed_clock, cap
):
    cap(7)
    await _subscription(
        db,
        subscribed,
        status="trialing",
        trial_start=_utc(2026, 10, 7, 9),
        trial_end=_utc(2026, 10, 14, 9),
    )
    await _store_attempts(db, user.id, [_utc(2026, 10, 8)])

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 409


async def test_a_user_behind_on_payment_is_told_to_update_their_payment_method(
    client, db, user, subscribed, with_author, fake_llm, fixed_clock, cap
):
    cap(1)
    await _subscription(db, subscribed, status="past_due")
    await _store_attempts(db, user.id, [_utc(2026, 10, 2)])

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.json()["way_out"] == "update_payment"


async def test_feedback_with_no_generations_left_is_refused_the_same_way(
    client, db, user, subscribed, with_author, fake_llm, fixed_clock, cap
):
    cap(2)
    fake_llm.replies = [written("sketch"), {"post": "final"}]
    post_id = (await client.post(POSTS, json={"brief": "ship"})).json()["id"]
    await _store_attempts(db, user.id, [_utc(2026, 10, 2)])
    fake_llm.calls.clear()

    response = await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "shorter"})

    assert response.status_code == 409
    assert response.json()["code"] == "ALLOWANCE_USED_UP"
    assert response.json()["resets_at"] == _iso(_utc(2026, 11, 1))
    assert fake_llm.calls == []
    # The refusal doesn't leave the Text held, so a restore still works.
    assert (await client.post(f"{POSTS}/{post_id}/versions/1/restore")).status_code == 200


async def test_restoring_a_version_and_editing_the_text_use_no_generation(
    client, db, user, subscribed, with_author, fake_llm, fixed_clock, cap
):
    cap(2)
    fake_llm.replies = [written("sketch"), {"post": "final"}]
    post_id = (await client.post(POSTS, json={"brief": "ship"})).json()["id"]
    await client.put(f"{POSTS}/{post_id}/text", json={"parts": ["edited by hand"]})
    fake_llm.replies = [written("sketch 2"), {"post": "final 2"}]

    response = await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "shorter"})

    assert response.status_code == 201


async def test_an_instance_that_sells_no_plans_has_no_generation_limit(
    client, db, user, sells_no_plans, with_author, fake_llm, fixed_clock, cap
):
    cap(1)
    await _store_attempts(db, user.id, [_utc(2026, 10, 2)])
    fake_llm.replies = [written("sketch"), {"post": "final"}]

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 201


async def test_an_empty_cap_means_no_generation_limit(
    client, db, user, subscribed, with_author, fake_llm, fixed_clock, cap
):
    cap(None)
    await _store_attempts(db, user.id, _times(_utc(2026, 10, 2), 600))
    fake_llm.replies = [written("sketch"), {"post": "final"}]

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 201


@dataclass
class _FillsTheAllowanceWhileWriting(FakeLLM):
    """A model that, on its first call, lets a concurrent request use the last Generation."""

    fill: Any = None

    async def structured(self, **kwargs: Any) -> StructuredResult[Any]:
        if self.fill is not None:
            fill, self.fill = self.fill, None
            await fill()
        return await super().structured(**kwargs)


async def test_a_version_written_while_a_concurrent_request_filled_the_allowance_is_kept(
    client, db, user, subscribed, with_author, fixed_clock, cap
):
    cap(1)
    llm = _FillsTheAllowanceWhileWriting(replies=[written("sketch"), {"post": "final"}])
    llm.fill = lambda: _store_attempts(db, user.id, [_utc(2026, 10, 10, 12)])
    app.dependency_overrides[get_llm] = lambda: llm

    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 201
    post_id = response.json()["id"]
    assert (await client.get(f"{POSTS}/{post_id}")).json()["versions"][0]["number"] == 1
