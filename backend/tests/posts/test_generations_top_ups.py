"""
Spending Top-ups on Generations (ADR 0017): only once the Allowance is used up, from the
unexpired Top-up that expires first, and only while Subscribed.
"""

from datetime import datetime, timedelta, timezone

import pytest

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.billing.gateway import OneOffPrice, TopUpPurchase
from pumpkit.billing.models import Subscription
from pumpkit.core.config import settings
from pumpkit.posts.llm import LLMError
from pumpkit.posts.models import Post, VersionAttempt
from tests.posts.writing_replies import written

AUTHORS = "/api/v1/inspiration-authors"
POSTS = "/api/v1/posts"
USAGE = "/api/v1/usage"
WEBHOOK = "/api/v1/stripe/webhook"
CUSTOMER = "cus_1"


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
async def with_author(client, subscribed, fake_x_reader):
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(post_id="levelsio-0", text="levelsio post", posted_at=_utc(2026, 9, 1))
    ]
    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201


@pytest.fixture
async def sells_top_ups(db, user, monkeypatch, fake_billing):
    """Allowances of 4 Generations, so a Top-up adds 2; `user` is Stripe's `CUSTOMER`."""
    monkeypatch.setattr(settings, "BILLING_TOP_UP_KEY", "pumpkit_top_up")
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 4)
    fake_billing.prices = [
        OneOffPrice(key="pumpkit_top_up", price_id="price_top_up", amount=1000, currency="eur")
    ]
    user.stripe_customer_id = CUSTOMER
    await db.commit()


async def _buy_top_up(client, fake_billing, session_id: str, paid_at: datetime) -> None:
    fake_billing.set_top_up(
        CUSTOMER, TopUpPurchase(checkout_session_id=session_id, paid_at=paid_at, reversed=False)
    )
    payload, signature = fake_billing.signed_event(
        event_id=f"evt_{session_id}",
        event_type="checkout.session.completed",
        data_object={"customer": CUSTOMER},
    )
    response = await client.post(WEBHOOK, content=payload, headers={"stripe-signature": signature})
    assert response.status_code == 200


async def _use_allowance(db, user_id: str, count: int = 4) -> None:
    """`count` Versions written on 2 October, in the `subscribed` fixture's October period."""
    start = _utc(2026, 10, 2)
    post = Post(user_id=user_id, brief="earlier", corpus_post_ids=[], created_at=start)
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
                created_at=start + timedelta(minutes=sequence),
            )
        )
    await db.commit()


async def _generations_left(client) -> tuple[int, list[int]]:
    """What the Allowance has left of its Generations, and what each Top-up has left."""
    allowance = (await client.get(USAGE)).json()["allowance"]
    return (
        allowance["generations"]["left"],
        [top_up["generations_left"] for top_up in allowance["top_ups"]],
    )


async def _start_post(client, fake_llm):
    fake_llm.replies = [written("sketch"), {"post": "final"}]
    return await client.post(POSTS, json={"brief": "ship"})


async def test_with_the_allowance_used_up_a_version_is_charged_to_a_top_up(
    client, db, user, subscribed, with_author, sells_top_ups, fake_llm, fake_billing, fixed_clock
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _use_allowance(db, user.id)

    response = await _start_post(client, fake_llm)

    assert response.status_code == 201
    assert await _generations_left(client) == (0, [1])


async def test_a_top_up_is_untouched_while_the_allowance_has_room(
    client, db, user, subscribed, with_author, sells_top_ups, fake_llm, fake_billing, fixed_clock
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _use_allowance(db, user.id, count=3)

    assert (await _start_post(client, fake_llm)).status_code == 201
    assert await _generations_left(client) == (0, [2])


async def test_feedback_is_charged_to_a_top_up_too(
    client, db, user, subscribed, with_author, sells_top_ups, fake_llm, fake_billing, fixed_clock
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    post_id = (await _start_post(client, fake_llm)).json()["id"]
    await _use_allowance(db, user.id, count=3)
    fake_llm.replies = [written("sketch 2"), {"post": "final 2"}]

    response = await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "shorter"})

    assert response.status_code == 201
    assert await _generations_left(client) == (0, [1])


async def test_the_top_up_that_expires_first_is_spent_first(
    client, db, user, subscribed, with_author, sells_top_ups, fake_llm, fake_billing, fixed_clock
):
    await _buy_top_up(client, fake_billing, "cs_later", _utc(2026, 10, 5))
    await _buy_top_up(client, fake_billing, "cs_sooner", _utc(2026, 10, 1))
    await _use_allowance(db, user.id)

    for _ in range(3):
        assert (await _start_post(client, fake_llm)).status_code == 201

    top_ups = (await client.get(USAGE)).json()["allowance"]["top_ups"]
    assert [(t["expires_at"], t["generations_left"]) for t in top_ups] == [
        ("2027-10-01T00:00:00Z", 0),
        ("2027-10-05T00:00:00Z", 1),
    ]


async def test_with_the_allowance_and_top_ups_used_up_the_way_out_is_a_top_up(
    client, db, user, subscribed, with_author, sells_top_ups, fake_llm, fake_billing, fixed_clock
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _use_allowance(db, user.id)
    for _ in range(2):
        assert (await _start_post(client, fake_llm)).status_code == 201
    fake_llm.calls.clear()

    response = await _start_post(client, fake_llm)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "You've used this period's 4 generations. They reset on 1 November. "
        "Failed attempts don't count."
    )
    assert (response.json()["left"], response.json()["way_out"]) == (0, "top_up")
    assert fake_llm.calls == []


async def test_an_expired_top_up_is_not_spent(
    client, db, user, subscribed, with_author, sells_top_ups, fake_llm, fake_billing, fixed_clock
):
    await _buy_top_up(client, fake_billing, "cs_old", _utc(2025, 10, 9))
    await _use_allowance(db, user.id)

    response = await _start_post(client, fake_llm)

    assert response.status_code == 409
    assert response.json()["way_out"] == "top_up"


async def test_a_failed_attempt_takes_nothing_from_a_top_up(
    client, db, user, subscribed, with_author, sells_top_ups, fake_llm, fake_billing, fixed_clock
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _use_allowance(db, user.id)
    fake_llm.replies = [LLMError("down")]

    assert (await client.post(POSTS, json={"brief": "ship"})).status_code == 502

    assert await _generations_left(client) == (0, [2])


async def test_a_top_up_bought_before_a_subscription_ended_is_spent_in_the_next_one(
    client, db, user, subscribed, with_author, sells_top_ups, fake_llm, fake_billing, fixed_clock
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 9, 3))
    subscribed.status = "canceled"
    db.add(subscribed)
    db.add(
        Subscription(
            user_id=user.id,
            stripe_subscription_id="sub_next",
            stripe_customer_id=CUSTOMER,
            status="active",
            stripe_created_at=_utc(2026, 10, 1),
        )
    )
    await db.commit()
    await _use_allowance(db, user.id)

    assert (await _start_post(client, fake_llm)).status_code == 201
    assert await _generations_left(client) == (0, [1])


async def test_a_user_who_isnt_subscribed_spends_no_top_up(
    client, db, user, subscribed, sells_top_ups, fake_llm, fake_billing, fixed_clock
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    subscribed.status = "canceled"
    db.add(subscribed)
    await db.commit()

    response = await _start_post(client, fake_llm)

    assert response.status_code == 403
    assert (await client.get(USAGE)).json() == {"allowance": None}
