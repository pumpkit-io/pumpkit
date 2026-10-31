"""
Spending Top-ups on X posts and link posts (ADR 0017): only what the Allowance period an X post
publishes in can't cover, from the Top-up that expires first and is still unexpired at the
publish time.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

import pumpkit.scheduling.service as scheduled_posts_service
from pumpkit.billing.gateway import OneOffPrice, TopUpPurchase
from pumpkit.core.config import settings
from pumpkit.scheduling.publisher import run_pass
from pumpkit.x_connection.x_publisher import XPostRejectedError, XRateLimitedError

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
USAGE = "/api/v1/usage"
WEBHOOK = "/api/v1/stripe/webhook"
CUSTOMER = "cus_1"


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
async def ready(db, user, subscribed, connect_x, fixed_clock, monkeypatch, fake_billing):
    """
    Subscribed on 10 October with periods from 14 September at 09:00, X connected, Allowances of
    4 X posts and 2 link posts, so a Top-up adds 2 and 1; `user` is Stripe's `CUSTOMER`.
    """
    monkeypatch.setattr(settings, "BILLING_TOP_UP_KEY", "pumpkit_top_up")
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 4)
    monkeypatch.setattr(settings, "X_LINK_POSTS_MONTHLY_CAP", 2)
    fake_billing.prices = [
        OneOffPrice(key="pumpkit_top_up", price_id="price_top_up", amount=1000, currency="eur")
    ]
    subscribed.billing_cycle_anchor = _utc(2026, 9, 14, 9)
    user.stripe_customer_id = CUSTOMER
    db.add_all([subscribed, user])
    await db.commit()
    await connect_x()


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


async def _schedule(client: AsyncClient, post_with, publish_at: str, *parts: str):
    return await client.post(
        SCHEDULED_POSTS, json={"post_id": await post_with(*parts), "publish_at": publish_at}
    )


async def _x_posts_left(client) -> tuple[int, list[int]]:
    """What the Allowance has left of its X posts, and what each Top-up has left."""
    allowance = (await client.get(USAGE)).json()["allowance"]
    return (
        allowance["x_posts"]["left"],
        [top_up["x_posts_left"] for top_up in allowance["top_ups"]],
    )


async def test_a_thread_the_allowance_covers_in_part_takes_the_rest_from_a_top_up(
    client, ready, post_with, fake_billing
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "Earlier")

    response = await _schedule(client, post_with, "2026-10-12T09:00:00Z", *["Part"] * 5)

    assert response.status_code == 201
    assert await _x_posts_left(client) == (0, [0])


async def test_an_action_the_allowance_and_top_ups_cant_cover_together_is_refused_whole(
    client, ready, post_with, fake_billing
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "Earlier")

    response = await _schedule(client, post_with, "2026-10-12T09:00:00Z", *["Part"] * 6)

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == (
        "This thread needs 6 X posts and you have 5 left. "
        "Buy a top-up or schedule it after 14 October. Failed posts don't count."
    )
    assert (body["ran_out"], body["needed"], body["left"]) == ("x_posts", 6, 5)
    assert await _x_posts_left(client) == (3, [2])


async def test_a_top_up_is_untouched_while_the_allowance_has_room(
    client, ready, post_with, fake_billing
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))

    response = await _schedule(client, post_with, "2026-10-12T09:00:00Z", *["Part"] * 4)

    assert response.status_code == 201
    assert await _x_posts_left(client) == (0, [2])


async def test_the_top_up_that_expires_first_is_spent_first(client, ready, post_with, fake_billing):
    await _buy_top_up(client, fake_billing, "cs_new", _utc(2026, 10, 3))
    await _buy_top_up(client, fake_billing, "cs_old", _utc(2025, 11, 1))
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", *["Part"] * 4)

    response = await _schedule(client, post_with, "2026-10-12T09:00:00Z", *["Part"] * 3)

    assert response.status_code == 201
    assert await _x_posts_left(client) == (0, [0, 1])


async def test_post_now_takes_from_a_top_up(client, ready, post_with, fake_billing):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", *["Part"] * 4)

    response = await client.post(
        SCHEDULED_POSTS, json={"post_id": await post_with("Now"), "publish_now": True}
    )

    assert response.json()["state"] == "published"
    assert await _x_posts_left(client) == (0, [1])


async def test_deleting_a_waiting_scheduled_post_gives_its_x_posts_back_to_the_top_up(
    client, ready, post_with, fake_billing
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    thread = await _schedule(client, post_with, "2026-10-12T09:00:00Z", *["Part"] * 5)

    response = await client.delete(f"{SCHEDULED_POSTS}/{thread.json()['id']}")

    assert response.status_code == 204
    assert await _x_posts_left(client) == (4, [2])


async def _post_now_failing(client, fake_x_publisher, post_id: str, *, on_part: int) -> None:
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = on_part
    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert response.json()["state"] == "failed", response.text
    fake_x_publisher.fail_publish = None
    fake_x_publisher.fail_publish_on = None


async def test_parts_that_fail_without_x_accepting_them_give_their_x_posts_back(
    client, ready, post_with, fake_billing, fake_x_publisher
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "Earlier")

    await _post_now_failing(client, fake_x_publisher, await post_with(*["Part"] * 5), on_part=5)

    assert await _x_posts_left(client) == (0, [1])


async def test_deleting_a_failed_thread_keeps_the_x_posts_x_accepted_counted_and_charged(
    client, ready, post_with, fake_billing, fake_x_publisher
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "Earlier")
    post_id = await post_with(*["Part"] * 5)
    await _post_now_failing(client, fake_x_publisher, post_id, on_part=5)
    failed = (await client.get(f"/api/v1/posts/{post_id}")).json()["scheduled_post"]

    response = await client.delete(f"{SCHEDULED_POSTS}/{failed['id']}")

    assert response.status_code == 204
    assert await _x_posts_left(client) == (0, [1])


async def test_deleting_a_thread_waiting_to_retry_keeps_its_live_parts_counted(
    client, ready, post_with, fake_billing, fake_x_publisher
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    fake_x_publisher.fail_publish = XRateLimitedError()
    fake_x_publisher.fail_publish_on = 4
    response = await client.post(
        SCHEDULED_POSTS, json={"post_id": await post_with(*["Part"] * 5), "publish_now": True}
    )
    assert response.json()["state"] == "scheduled", response.text

    await client.delete(f"{SCHEDULED_POSTS}/{response.json()['id']}")

    assert await _x_posts_left(client) == (1, [2])


async def test_a_post_that_fails_before_x_accepts_anything_gives_back_every_x_post(
    client, ready, post_with, fake_billing, fake_x_publisher
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "Earlier")

    await _post_now_failing(client, fake_x_publisher, await post_with(*["Part"] * 5), on_part=1)

    assert await _x_posts_left(client) == (3, [2])


async def test_a_post_a_crash_left_publishing_gives_back_the_x_posts_x_never_accepted(
    client, ready, post_with, fake_billing, fake_x_publisher, db_session_maker, fixed_clock
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "Earlier")
    thread = await _schedule(client, post_with, "2026-10-10T12:02:00Z", *["Part"] * 5)
    fixed_clock.advance(timedelta(minutes=2))
    async with db_session_maker() as session:
        assert await scheduled_posts_service.claim(
            session, scheduled_post_id=thread.json()["id"], now=fixed_clock()
        )
        await session.commit()
    fixed_clock.advance(timedelta(minutes=10, seconds=30))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert await _x_posts_left(client) == (3, [2])


async def test_a_top_up_expired_by_the_publish_time_is_not_charged(
    client, ready, post_with, fake_billing
):
    # Lasts until 20 October 2026, inside the period from 14 October.
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2025, 10, 20))
    await _schedule(client, post_with, "2026-10-15T09:00:00Z", *["Part"] * 4)

    before_expiry = await _schedule(client, post_with, "2026-10-19T09:00:00Z", "Before")
    after_expiry = await _schedule(client, post_with, "2026-10-21T09:00:00Z", "After")

    assert before_expiry.status_code == 201
    assert after_expiry.status_code == 409
    assert after_expiry.json()["left"] == 0
    assert await _x_posts_left(client) == (4, [1])


async def test_an_edit_adding_parts_takes_them_from_a_top_up(
    client, ready, post_with, fake_billing
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    single = (await _schedule(client, post_with, "2026-10-12T09:00:00Z", "One")).json()

    response = await client.patch(f"{SCHEDULED_POSTS}/{single['id']}", json={"parts": ["Part"] * 6})

    assert response.status_code == 200
    assert await _x_posts_left(client) == (0, [0])


async def test_an_edit_counts_what_the_post_took_from_a_top_up_as_the_top_ups_again(
    client, ready, post_with, fake_billing
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    thread = (await _schedule(client, post_with, "2026-10-12T09:00:00Z", *["Part"] * 5)).json()

    grown = await client.patch(f"{SCHEDULED_POSTS}/{thread['id']}", json={"parts": ["Part"] * 6})
    too_long = await client.patch(f"{SCHEDULED_POSTS}/{thread['id']}", json={"parts": ["Part"] * 7})

    assert grown.status_code == 200
    assert too_long.status_code == 409
    assert too_long.json()["left"] == 6


async def test_moving_a_post_to_another_period_charges_it_afresh_there(
    client, ready, post_with, fake_billing
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "Earlier")
    thread = (await _schedule(client, post_with, "2026-10-12T09:00:00Z", *["Part"] * 5)).json()

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{thread['id']}", json={"publish_at": "2026-10-20T09:00:00Z"}
    )

    assert response.status_code == 200
    # The period from 14 October covers 4 of its 5 Parts.
    assert await _x_posts_left(client) == (3, [1])


async def test_link_posts_beyond_the_allowance_are_charged_to_a_top_up(
    client, ready, post_with, fake_billing
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))

    fits = await _schedule(client, post_with, "2026-10-12T09:00:00Z", "a.com", "b.com", "c.com")
    refused = await _schedule(client, post_with, "2026-10-12T10:00:00Z", "d.com")

    assert fits.status_code == 201
    assert refused.status_code == 409
    assert refused.json()["ran_out"] == "link_x_posts"
    usage = (await client.get(USAGE)).json()["allowance"]
    assert usage["link_x_posts"]["left"] == 0
    assert [top_up["link_x_posts_left"] for top_up in usage["top_ups"]] == [0]


async def test_a_top_up_bought_after_a_post_published_pays_nothing_for_it(
    client, ready, post_with, fake_billing, fake_x_publisher, monkeypatch
):
    await _post_now_failing(client, fake_x_publisher, await post_with(*["Part"] * 4), on_part=4)
    later = (await _schedule(client, post_with, "2026-10-12T09:00:00Z", "Waiting")).json()
    # An Operator lowers the cap, so the Failed thread's 3 live Parts are over the Allowance.
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 2)
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 10, 13))

    await client.delete(f"{SCHEDULED_POSTS}/{later['id']}")

    assert await _x_posts_left(client) == (0, [1])


@pytest.fixture
async def later_post_on_a_top_up(client, ready, post_with, fake_billing):
    """A Thread using the whole Allowance from 11 October, then a post on 12 October on a Top-up."""
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    thread = (await _schedule(client, post_with, "2026-10-11T09:00:00Z", *["Part"] * 4)).json()
    await _schedule(client, post_with, "2026-10-12T09:00:00Z", "Later")
    assert await _x_posts_left(client) == (0, [1])
    return thread


async def test_deleting_a_post_moves_a_later_one_off_the_top_up_onto_the_allowance(
    client, later_post_on_a_top_up
):
    await client.delete(f"{SCHEDULED_POSTS}/{later_post_on_a_top_up['id']}")

    assert await _x_posts_left(client) == (3, [2])


async def test_moving_a_post_to_another_period_moves_a_later_one_onto_the_allowance(
    client, later_post_on_a_top_up
):
    response = await client.patch(
        f"{SCHEDULED_POSTS}/{later_post_on_a_top_up['id']}",
        json={"publish_at": "2026-10-20T09:00:00Z"},
    )

    assert response.status_code == 200
    assert await _x_posts_left(client) == (3, [2])


async def test_an_edit_dropping_parts_moves_a_later_post_onto_the_allowance(
    client, later_post_on_a_top_up
):
    response = await client.patch(
        f"{SCHEDULED_POSTS}/{later_post_on_a_top_up['id']}", json={"parts": ["One", "Two"]}
    )

    assert response.status_code == 200
    assert await _x_posts_left(client) == (1, [2])


async def test_a_post_failing_at_the_publisher_moves_a_later_one_onto_the_allowance(
    client, ready, post_with, fake_billing, fake_x_publisher, db_session_maker, fixed_clock
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _schedule(client, post_with, "2026-10-10T12:02:00Z", *["Part"] * 4)
    await _schedule(client, post_with, "2026-10-12T09:00:00Z", "Later")
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fixed_clock.advance(timedelta(minutes=3))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert await _x_posts_left(client) == (3, [2])


async def test_a_post_that_would_push_a_later_one_onto_an_expired_top_up_is_refused(
    client, ready, post_with, fake_billing
):
    # Lasts until 12 October 2026, between the new post and the Thread after it.
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2025, 10, 12))
    await _schedule(client, post_with, "2026-10-13T09:00:00Z", *["Part"] * 4)

    response = await _schedule(client, post_with, "2026-10-11T09:00:00Z", "One", "Two")

    assert response.status_code == 409
    assert (response.json()["ran_out"], response.json()["left"]) == ("x_posts", 0)
    assert await _x_posts_left(client) == (0, [2])


async def test_an_edit_that_would_push_a_later_post_onto_an_expired_top_up_is_refused(
    client, ready, post_with, fake_billing
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2025, 10, 12))
    await _schedule(client, post_with, "2026-10-13T09:00:00Z", *["Part"] * 3)
    single = (await _schedule(client, post_with, "2026-10-14T08:00:00Z", "One")).json()

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{single['id']}",
        json={"publish_at": "2026-10-11T09:00:00Z", "parts": ["One", "Two"]},
    )

    assert response.status_code == 409
    assert await _x_posts_left(client) == (0, [2])


async def test_a_period_already_over_its_allowance_accepts_a_move_needing_no_more_room(
    client, ready, post_with, monkeypatch
):
    thread = (await _schedule(client, post_with, "2026-10-11T09:00:00Z", *["Part"] * 4)).json()
    # An Operator lowers the cap, so the period is over its Allowance.
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 2)

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{thread['id']}", json={"publish_at": "2026-10-12T09:00:00Z"}
    )

    assert response.status_code == 200


async def test_moving_a_post_into_an_earlier_period_may_not_starve_the_later_one_of_top_ups(
    client, ready, post_with, fake_billing
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _buy_top_up(client, fake_billing, "cs_2", _utc(2026, 10, 4))
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", *["Part"] * 4)
    mover = (await _schedule(client, post_with, "2026-10-15T09:00:00Z", "Mover")).json()
    await _schedule(client, post_with, "2026-10-16T09:00:00Z", *["Part"] * 5)

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{mover['id']}",
        json={"publish_at": "2026-10-12T09:00:00Z", "parts": ["Mover"] * 4},
    )

    assert response.status_code == 409
    assert (response.json()["needed"], response.json()["left"]) == (4, 3)


async def _refund(client, fake_billing, session_id: str, paid_at: datetime) -> None:
    fake_billing.set_top_up(
        CUSTOMER, TopUpPurchase(checkout_session_id=session_id, paid_at=paid_at, reversed=True)
    )
    payload, signature = fake_billing.signed_event(
        event_id=f"evt_refund_{session_id}",
        event_type="charge.refunded",
        data_object={"customer": CUSTOMER},
    )
    response = await client.post(WEBHOOK, content=payload, headers={"stripe-signature": signature})
    assert response.status_code == 200


async def test_a_refunded_top_up_keeps_what_it_paid_for_off_the_allowance(
    client, ready, post_with, fake_billing
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", *["Part"] * 5)

    await _refund(client, fake_billing, "cs_1", _utc(2026, 10, 3))

    x_posts = (await client.get(USAGE)).json()["allowance"]["x_posts"]
    assert (x_posts["used"], x_posts["left"]) == (4, 0)
    assert await _x_posts_left(client) == (0, [])


async def test_a_waiting_post_keeps_its_charge_on_a_refunded_top_up_when_its_period_changes(
    client, ready, post_with, fake_billing
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    earlier = (await _schedule(client, post_with, "2026-10-11T09:00:00Z", "Earlier")).json()
    await _schedule(client, post_with, "2026-10-12T09:00:00Z", *["Part"] * 4)
    await _refund(client, fake_billing, "cs_1", _utc(2026, 10, 3))

    await client.delete(f"{SCHEDULED_POSTS}/{earlier['id']}")

    assert await _x_posts_left(client) == (1, [])


async def test_a_post_shrunk_after_a_refund_keeps_only_what_it_still_uses_off_the_allowance(
    client, ready, post_with, fake_billing
):
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2026, 10, 3))
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "One", "Two")
    thread = (await _schedule(client, post_with, "2026-10-12T09:00:00Z", *["Part"] * 4)).json()
    await _refund(client, fake_billing, "cs_1", _utc(2026, 10, 3))

    response = await client.patch(f"{SCHEDULED_POSTS}/{thread['id']}", json={"parts": ["Part"]})

    assert response.status_code == 200
    assert await _x_posts_left(client) == (2, [])


async def test_usage_at_a_later_moment_reports_its_period_and_the_top_ups_unexpired_then(
    client, ready, post_with, fake_billing
):
    # Lasts until 20 October 2026, inside the period from 14 October.
    await _buy_top_up(client, fake_billing, "cs_1", _utc(2025, 10, 20))
    await _schedule(client, post_with, "2026-10-15T09:00:00Z", "Next period")

    now = (await client.get(USAGE)).json()["allowance"]
    later = (await client.get(USAGE, params={"at": "2026-10-21T09:00:00Z"})).json()["allowance"]

    assert (now["resets_at"], now["x_posts"]["used"], len(now["top_ups"])) == (
        "2026-10-14T09:00:00Z",
        0,
        1,
    )
    assert (later["resets_at"], later["x_posts"]["used"], later["top_ups"]) == (
        "2026-11-14T09:00:00Z",
        1,
        [],
    )
