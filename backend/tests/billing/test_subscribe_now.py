"""A Trial User subscribes now: the Trial ends in Stripe at once and the paid Allowance starts."""

from datetime import datetime, timedelta, timezone

import pytest

import pumpkit.billing.service as billing_service
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.billing.gateway import SubscriptionState
from pumpkit.billing.subscription_status import SubscriptionStatus
from pumpkit.core.config import settings
from pumpkit.posts.models import Post, VersionAttempt
from tests.posts.writing_replies import written

CUSTOMER = "cus_alice"
SUBSCRIBE_NOW = "/api/v1/billing/subscribe-now"
USAGE = "/api/v1/usage"
POSTS = "/api/v1/posts"
AUTHORS = "/api/v1/inspiration-authors"


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


TRIAL_START = _utc(2026, 10, 7, 9)
TRIAL_END = _utc(2026, 10, 14, 9)


@pytest.fixture(autouse=True)
def caps(monkeypatch):
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 500)
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 100)
    monkeypatch.setattr(settings, "X_LINK_POSTS_MONTHLY_CAP", 10)


def _state(status: SubscriptionStatus) -> SubscriptionState:
    return SubscriptionState(
        id="sub_1",
        status=status,
        price_id="price_monthly",
        plan_key="pumpkit_pro_monthly",
        current_period_end=TRIAL_END,
        cancel_at_period_end=False,
        created_at=TRIAL_START,
        trial_start=TRIAL_START,
        trial_end=TRIAL_END,
        billing_cycle_anchor=TRIAL_END,
    )


@pytest.fixture
async def holds(db, user, fake_billing, fixed_clock):
    """Make Stripe and Pumpkit's copy hold the User's Subscription in a status, as a webhook would."""
    user.stripe_customer_id = CUSTOMER
    await db.commit()
    fake_billing.clock = fixed_clock

    async def _holds(status: SubscriptionStatus) -> None:
        fake_billing.set_subscription(CUSTOMER, _state(status))
        await billing_service.sync_customer(db, fake_billing, user_id=user.id, customer_id=CUSTOMER)
        await db.commit()

    return _holds


async def _trial_attempts(db, user_id: str, count: int) -> None:
    post = Post(user_id=user_id, brief="earlier", corpus_post_ids=[], created_at=TRIAL_START)
    db.add(post)
    await db.flush()
    for sequence in range(1, count + 1):
        db.add(
            VersionAttempt(
                post_id=post.id,
                sequence=sequence,
                version_number=sequence,
                format="post",
                status="succeeded",
                parts=["earlier"],
                created_at=TRIAL_START + timedelta(minutes=sequence),
            )
        )
    await db.commit()


async def test_subscribing_now_ends_the_trial_and_starts_the_monthly_allowance(
    client, fake_billing, holds
):
    await holds("trialing")

    response = await client.post(SUBSCRIBE_NOW)

    assert response.status_code == 200
    assert response.json()["subscription"]["status"] == "active"
    assert response.json()["subscribed"] is True
    assert fake_billing.ended_trials == ["sub_1"]
    usage = (await client.get(USAGE)).json()["allowance"]
    assert usage["trial"] is False
    # The fixed clock reads 10 October 12:00:30, the new billing cycle anchor.
    assert usage["resets_at"] == "2026-11-10T12:00:30Z"
    assert usage["generations"] == {"limit": 500, "used": 0, "left": 500}
    assert usage["way_out"] is None


async def test_a_trial_user_at_the_trials_limit_can_write_again_once_subscribed(
    client, db, user, fake_billing, fake_x_reader, fake_llm, holds
):
    await holds("trialing")
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(post_id="levelsio-0", text="levelsio post", posted_at=_utc(2026, 9, 1))
    ]
    await client.post(AUTHORS, json={"handle": "levelsio"})
    await _trial_attempts(db, user.id, 125)
    assert (await client.post(POSTS, json={"brief": "ship"})).status_code == 409
    fake_llm.replies = [written("sketch"), {"post": "final"}]

    assert (await client.post(SUBSCRIBE_NOW)).status_code == 200
    response = await client.post(POSTS, json={"brief": "ship"})

    assert response.status_code == 201


async def test_a_failed_first_charge_leaves_the_subscription_past_due_and_says_so(
    client, fake_billing, holds
):
    await holds("trialing")
    fake_billing.first_charge_fails = True

    response = await client.post(SUBSCRIBE_NOW)

    assert response.status_code == 402
    assert response.json()["detail"] == (
        "Your trial has ended, but the first payment didn't go through. "
        "Update your payment method to keep writing."
    )
    me = (await client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["status"] == "past_due"
    assert me["subscribed"] is True


@pytest.mark.parametrize("status", ["active", "past_due", "canceled"])
async def test_a_user_who_isnt_trialing_cant_subscribe_now(client, fake_billing, holds, status):
    holds(status)

    response = await client.post(SUBSCRIBE_NOW)

    assert response.status_code == 409
    assert response.json()["detail"] == "You're not in a trial, so there's no trial to end."
    assert fake_billing.ended_trials == []


async def test_a_user_with_no_stripe_customer_cant_subscribe_now(client, fake_billing):
    response = await client.post(SUBSCRIBE_NOW)

    assert response.status_code == 409
    assert fake_billing.ended_trials == []
    assert fake_billing.customers_created == []


async def test_a_trial_stripe_has_already_ended_is_not_ended_again(client, fake_billing, holds):
    """Pumpkit's copy still says trialing, but the sync from Stripe runs first (ADR 0004)."""
    await holds("trialing")
    fake_billing.set_subscription(CUSTOMER, _state("active"))

    response = await client.post(SUBSCRIBE_NOW)

    assert response.status_code == 409
    me = (await client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["status"] == "active"


async def test_a_gateway_failure_ending_the_trial_returns_502(
    client, fake_billing, holds, assert_reported_502
):
    await holds("trialing")
    fake_billing.fail_on = {"end_trial"}

    response = await client.post(SUBSCRIBE_NOW)

    assert_reported_502(response)


async def test_subscribe_now_answers_404_where_no_plans_are_sold(
    client, sells_no_plans, fake_billing
):
    response = await client.post(SUBSCRIBE_NOW)

    assert response.status_code == 404
