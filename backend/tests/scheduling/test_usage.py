"""What a User has used and has left of their Allowance, over `GET /usage` and `get_usage`."""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from pumpkit.billing.models import Subscription
from pumpkit.core.config import settings
from pumpkit.posts.models import Post, VersionAttempt

USAGE = "/api/v1/usage"


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


@pytest.fixture
def caps(monkeypatch):
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 500)
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 100)
    monkeypatch.setattr(settings, "X_LINK_POSTS_MONTHLY_CAP", 10)


async def _subscription(db, subscription: Subscription, **fields: Any) -> None:
    for name, value in fields.items():
        setattr(subscription, name, value)
    db.add(subscription)
    await db.commit()


async def _attempts(db, user_id: str, start: datetime, count: int, status: str = "succeeded"):
    """One Post of `user_id` with `count` attempts a minute apart from `start`."""
    post = Post(user_id=user_id, brief="earlier", corpus_post_ids=[], created_at=start)
    db.add(post)
    await db.flush()
    for sequence in range(1, count + 1):
        db.add(
            VersionAttempt(
                post_id=post.id,
                sequence=sequence,
                version_number=sequence if status == "succeeded" else None,
                format="post",
                status=status,
                parts=["earlier"] if status == "succeeded" else None,
                error="LLMError: down" if status == "failed" else None,
                created_at=start + timedelta(minutes=sequence),
            )
        )
    await db.commit()


async def test_usage_counts_the_generations_written_this_period(
    client, db, user, subscribed, fixed_clock, caps
):
    await _subscription(db, subscribed, billing_cycle_anchor=_utc(2026, 9, 14, 9))
    await _attempts(db, user.id, _utc(2026, 9, 20), 4)
    await _attempts(db, user.id, _utc(2026, 9, 10), 6)
    await _attempts(db, user.id, _utc(2026, 9, 21), 2, status="failed")

    response = await client.get(USAGE)

    assert response.status_code == 200
    assert response.json() == {
        "allowance": {
            "trial": False,
            "resets_at": "2026-10-14T09:00:00Z",
            "resets_on_day": 14,
            "generations": {"limit": 500, "used": 4, "left": 496},
            "x_posts": {"limit": 100, "used": 0, "left": 100},
            "link_x_posts": {"limit": 10, "used": 0, "left": 10},
            "way_out": None,
            "top_ups": [],
            "may_buy_top_up": False,
        }
    }


async def test_periods_from_the_31st_reset_on_the_31st_even_in_a_shorter_month(
    client, db, subscribed, fixed_clock, caps
):
    await _subscription(db, subscribed, billing_cycle_anchor=_utc(2026, 8, 31, 9))

    allowance = (await client.get(USAGE)).json()["allowance"]

    assert (allowance["resets_at"], allowance["resets_on_day"]) == ("2026-10-31T09:00:00Z", 31)


async def test_a_trial_s_usage_counts_against_its_quarter_until_the_trial_ends(
    client, db, user, subscribed, fixed_clock, caps
):
    await _subscription(
        db,
        subscribed,
        status="trialing",
        trial_start=_utc(2026, 10, 7, 9),
        trial_end=_utc(2026, 10, 14, 9),
        billing_cycle_anchor=_utc(2026, 10, 14, 9),
    )
    await _attempts(db, user.id, _utc(2026, 10, 8), 27)

    allowance = (await client.get(USAGE)).json()["allowance"]

    assert allowance["trial"] is True
    assert allowance["resets_at"] == "2026-10-14T09:00:00Z"
    assert allowance["resets_on_day"] is None
    assert allowance["generations"] == {"limit": 125, "used": 27, "left": 98}
    assert allowance["x_posts"] == {"limit": 25, "used": 0, "left": 25}
    assert allowance["link_x_posts"] == {"limit": 2, "used": 0, "left": 2}
    assert allowance["way_out"] == "subscribe_now"


async def test_a_user_behind_on_payment_is_told_to_update_their_payment_method(
    client, db, subscribed, fixed_clock, caps
):
    await _subscription(db, subscribed, status="past_due")

    allowance = (await client.get(USAGE)).json()["allowance"]

    assert allowance["way_out"] == "update_payment"


async def test_an_empty_cap_is_no_limit(client, subscribed, fixed_clock, caps, monkeypatch):
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", None)

    allowance = (await client.get(USAGE)).json()["allowance"]

    assert allowance["generations"] == {"limit": None, "used": 0, "left": None}


async def test_a_user_who_isn_t_subscribed_has_no_allowance(client, fixed_clock):
    response = await client.get(USAGE)

    assert response.status_code == 200
    assert response.json() == {"allowance": None}


async def test_get_usage_answers_as_the_usage_route_does(
    client, db, user, subscribed, fixed_clock, caps, mcp
):
    await _attempts(db, user.id, _utc(2026, 10, 2), 3)

    result = await mcp.call_tool("get_usage")

    assert result["isError"] is False, result
    assert result["structuredContent"] == (await client.get(USAGE)).json()
    assert result["structuredContent"]["allowance"]["generations"]["used"] == 3


async def test_get_usage_without_plans_says_there_is_no_allowance(sells_no_plans, mcp):
    result = await mcp.call_tool("get_usage")

    assert result["isError"] is False, result
    assert result["structuredContent"] == {"allowance": None}


async def test_the_instructions_tell_claude_about_the_allowance(subscribed, mcp):
    instructions = (await mcp.initialize())["instructions"]

    assert "Each post started and each feedback uses one generation" in instructions
    assert "each X post published uses one X post" in instructions
    assert "`get_usage`" in instructions
