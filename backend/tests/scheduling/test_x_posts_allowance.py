"""
X posts and link posts of the Allowance (ADR 0017): each Part publishing in an Allowance period
counts against it, and one containing a link also against the link posts.
"""

from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from httpx import AsyncClient

from pumpkit.billing.models import Subscription
from pumpkit.core.config import settings
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.scheduling.reading import scheduled_posts

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
USAGE = "/api/v1/usage"
SETTINGS_URL = "http://localhost:5173/settings"


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


@pytest.fixture
def caps(monkeypatch):
    def _caps(x_posts: Optional[int] = 100, link_x_posts: Optional[int] = 10) -> None:
        monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", x_posts)
        monkeypatch.setattr(settings, "X_LINK_POSTS_MONTHLY_CAP", link_x_posts)

    return _caps


@pytest.fixture
async def ready(db, subscribed, connect_x, fixed_clock):
    """Subscribed with periods from 14 September at 09:00, X connected, on 10 October."""
    await _subscription(db, subscribed, billing_cycle_anchor=_utc(2026, 9, 14, 9))
    await connect_x()


async def _subscription(db, subscription: Subscription, **fields: Any) -> None:
    for name, value in fields.items():
        setattr(subscription, name, value)
    db.add(subscription)
    await db.commit()


async def _schedule(client: AsyncClient, post_with, publish_at: str, *parts: str):
    return await client.post(
        SCHEDULED_POSTS, json={"post_id": await post_with(*parts), "publish_at": publish_at}
    )


async def _failed(client: AsyncClient, fake_x_publisher, post_id: str, *, on_part: int = 1):
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = on_part
    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert response.json()["state"] == "failed", response.text
    fake_x_publisher.fail_publish = None
    fake_x_publisher.fail_publish_on = None
    return response.json()


async def test_scheduling_with_no_x_posts_left_is_refused_with_the_reset_date(
    client, ready, post_with, caps
):
    caps(x_posts=2)
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "One")
    await _schedule(client, post_with, "2026-10-12T09:00:00Z", "Two")

    response = await _schedule(client, post_with, "2026-10-13T09:00:00Z", "Three")

    assert response.status_code == 409
    assert response.json() == {
        "detail": (
            "You've used this period's 2 X posts. They reset on 14 October. "
            "Failed posts don't count."
        ),
        "url": SETTINGS_URL,
        "code": "ALLOWANCE_USED_UP",
        "ran_out": "x_posts",
        "needed": 1,
        "left": 0,
        "resets_at": _iso(_utc(2026, 10, 14, 9)),
        "way_out": None,
    }
    assert len(await scheduled_posts(client)) == 2


async def test_an_x_post_counts_against_the_period_its_publish_time_falls_in(
    client, ready, post_with, caps
):
    caps(x_posts=1)
    last_minute = await _schedule(client, post_with, "2026-10-14T08:59:00Z", "Last minute")
    next_period = await _schedule(client, post_with, "2026-10-14T09:00:00Z", "Next period")

    refused = await _schedule(client, post_with, "2026-10-13T09:00:00Z", "Too many")

    assert last_minute.status_code == next_period.status_code == 201
    assert refused.status_code == 409
    assert refused.json()["resets_at"] == _iso(_utc(2026, 10, 14, 9))


async def test_post_now_with_no_x_posts_left_is_refused(
    client, ready, post_with, caps, fake_x_publisher
):
    caps(x_posts=1)
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "One")

    response = await client.post(
        SCHEDULED_POSTS, json={"post_id": await post_with("Now"), "publish_now": True}
    )

    assert response.status_code == 409
    assert response.json()["ran_out"] == "x_posts"
    assert fake_x_publisher.published == []


async def test_a_thread_that_doesnt_fit_is_refused_whole_with_what_it_needs_and_has_left(
    client, ready, post_with, caps
):
    caps(x_posts=3)
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "First")

    response = await _schedule(client, post_with, "2026-10-12T09:00:00Z", "One", "Two", "Three")

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == (
        "This thread needs 3 X posts and you have 2 left. Schedule it after 14 October. "
        "Failed posts don't count."
    )
    assert (body["needed"], body["left"]) == (3, 2)
    assert len(await scheduled_posts(client)) == 1


async def test_an_x_post_with_a_link_also_uses_a_link_post(client, ready, post_with, caps):
    caps(link_x_posts=1)
    linked = await _schedule(client, post_with, "2026-10-11T09:00:00Z", "Read pumpkit.io today")

    refused = await _schedule(
        client, post_with, "2026-10-12T09:00:00Z", "See https://example.com/notes"
    )
    plain = await _schedule(client, post_with, "2026-10-12T09:00:00Z", "No link in this one.")

    assert linked.status_code == plain.status_code == 201
    assert refused.status_code == 409
    body = refused.json()
    assert body["detail"] == (
        "You've used this period's 1 X posts with a link. They reset on 14 October. "
        "Failed posts don't count."
    )
    assert (body["ran_out"], body["needed"], body["left"]) == ("link_x_posts", 1, 0)


async def test_each_part_with_a_link_is_one_link_post(client, ready, post_with, caps):
    caps(link_x_posts=2)

    response = await _schedule(
        client, post_with, "2026-10-11T09:00:00Z", "a.com", "No link", "b.org", "c.io"
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This thread needs 3 X posts with a link and you have 2 left. "
        "Schedule it after 14 October. Failed posts don't count."
    )


async def test_a_trial_gets_a_quarter_of_the_x_posts_and_link_posts(
    client, db, subscribed, connect_x, fixed_clock, post_with, caps
):
    caps(x_posts=100, link_x_posts=10)
    await _subscription(
        db,
        subscribed,
        status="trialing",
        trial_start=_utc(2026, 10, 7, 9),
        trial_end=_utc(2026, 10, 14, 9),
        billing_cycle_anchor=_utc(2026, 10, 14, 9),
    )
    await connect_x()
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "a.com")
    await _schedule(client, post_with, "2026-10-11T10:00:00Z", "b.com")

    refused = await _schedule(client, post_with, "2026-10-11T11:00:00Z", "c.com")
    thread = await _schedule(client, post_with, "2026-10-12T09:00:00Z", *["Part"] * 24)

    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "You've used your trial's 2 X posts with a link. Your trial ends on 14 October. "
        "Failed posts don't count."
    )
    assert refused.json()["way_out"] == "subscribe_now"
    assert thread.status_code == 409
    assert thread.json()["detail"] == (
        "This thread needs 24 X posts and you have 23 left in your trial. "
        "Subscribe now or schedule it after your trial ends on 14 October. "
        "Failed posts don't count."
    )


async def test_a_trial_whose_link_share_rounds_down_to_zero_refuses_links_clearly(
    client, db, subscribed, connect_x, fixed_clock, post_with, caps
):
    caps(x_posts=100, link_x_posts=3)
    await _subscription(
        db,
        subscribed,
        status="trialing",
        trial_start=_utc(2026, 10, 7, 9),
        trial_end=_utc(2026, 10, 14, 9),
        billing_cycle_anchor=_utc(2026, 10, 14, 9),
    )
    await connect_x()

    plain = await _schedule(client, post_with, "2026-10-11T09:00:00Z", "No link")
    refused = await _schedule(client, post_with, "2026-10-11T10:00:00Z", "Read a.com")

    assert plain.status_code == 201
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "Your trial doesn't include X posts with a link. Subscribe now or schedule it after "
        "your trial ends on 14 October."
    )
    assert (refused.json()["ran_out"], refused.json()["left"]) == ("link_x_posts", 0)


async def test_parts_of_a_failed_post_that_x_never_accepted_dont_count(
    client, ready, post_with, caps, fake_x_publisher
):
    caps(x_posts=1)
    await _failed(client, fake_x_publisher, await post_with("Refused"))

    response = await _schedule(client, post_with, "2026-10-11T09:00:00Z", "Another")

    assert response.status_code == 201


async def test_accepted_parts_of_a_failed_thread_keep_counting(
    client, ready, post_with, caps, fake_x_publisher
):
    caps(x_posts=2)
    await _failed(client, fake_x_publisher, await post_with("Live", "Refused"), on_part=2)
    fits = await _schedule(client, post_with, "2026-10-11T09:00:00Z", "Fits")

    refused = await _schedule(client, post_with, "2026-10-11T10:00:00Z", "Doesn't fit")

    assert fits.status_code == 201
    assert refused.status_code == 409


async def test_unscheduling_a_waiting_scheduled_post_gives_its_x_posts_back(
    client, ready, post_with, caps
):
    caps(x_posts=2)
    thread = await _schedule(client, post_with, "2026-10-11T09:00:00Z", "One", "Two")
    await client.delete(f"{SCHEDULED_POSTS}/{thread.json()['id']}")

    response = await _schedule(client, post_with, "2026-10-12T09:00:00Z", "Three", "Four")

    assert response.status_code == 201


async def test_an_edit_adding_parts_that_dont_fit_is_refused(client, ready, post_with, caps):
    caps(x_posts=2)
    single = (await _schedule(client, post_with, "2026-10-11T09:00:00Z", "One")).json()

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{single['id']}", json={"parts": ["One", "Two", "Three"]}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This thread needs 3 X posts and you have 2 left. Schedule it after 14 October. "
        "Failed posts don't count."
    )


async def test_an_edit_adding_a_link_that_doesnt_fit_is_refused(client, ready, post_with, caps):
    caps(link_x_posts=1)
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "pumpkit.io")
    plain = (await _schedule(client, post_with, "2026-10-12T09:00:00Z", "Plain")).json()

    linked = await client.patch(f"{SCHEDULED_POSTS}/{plain['id']}", json={"parts": ["x.com"]})
    reworded = await client.patch(f"{SCHEDULED_POSTS}/{plain['id']}", json={"parts": ["Plainer"]})

    assert linked.status_code == 409
    assert linked.json()["ran_out"] == "link_x_posts"
    assert reworded.status_code == 200


async def test_moving_a_scheduled_post_into_a_full_period_is_refused(
    client, ready, post_with, caps
):
    caps(x_posts=1)
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "This period")
    later = (await _schedule(client, post_with, "2026-10-20T09:00:00Z", "Next period")).json()

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{later['id']}", json={"publish_at": "2026-10-12T09:00:00Z"}
    )

    assert response.status_code == 409
    assert response.json()["ran_out"] == "x_posts"


async def test_an_empty_link_cap_means_no_link_limit(client, ready, post_with, caps):
    caps(link_x_posts=None)

    response = await _schedule(
        client, post_with, "2026-10-11T09:00:00Z", *[f"site{n}.com" for n in range(12)]
    )

    assert response.status_code == 201


async def test_without_plans_link_posts_count_per_calendar_month(
    client, sells_no_plans, connect_x, fixed_clock, post_with, caps
):
    caps(link_x_posts=1)
    await connect_x()
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "pumpkit.io")
    november = await _schedule(client, post_with, "2026-11-01T00:00:00Z", "pumpkit.io")

    refused = await _schedule(client, post_with, "2026-10-12T09:00:00Z", "x.com")

    assert november.status_code == 201
    assert refused.status_code == 409
    assert refused.json() == {
        "detail": (
            "You have 1 X posts with a link in October 2026, the most for one month. "
            "The limit resets on November 1, 2026."
        )
    }


async def test_without_plans_failed_parts_x_never_accepted_dont_count(
    client, sells_no_plans, connect_x, fixed_clock, post_with, caps, fake_x_publisher
):
    caps(x_posts=1)
    await connect_x()
    await _failed(client, fake_x_publisher, await post_with("Refused"))

    response = await _schedule(client, post_with, "2026-10-11T09:00:00Z", "Another")

    assert response.status_code == 201


async def test_usage_says_how_many_x_posts_and_link_posts_are_left(client, ready, post_with, caps):
    caps(x_posts=5, link_x_posts=2)
    await _schedule(client, post_with, "2026-10-11T09:00:00Z", "pumpkit.io", "Plain")
    await _schedule(client, post_with, "2026-10-20T09:00:00Z", "Next period")

    response = await client.get(USAGE)

    assert response.status_code == 200
    assert response.json() == {
        "allowance": {
            "trial": False,
            "resets_at": _iso(_utc(2026, 10, 14, 9)),
            "resets_on_day": 14,
            "generations": {"limit": 500, "used": 0, "left": 500},
            "x_posts": {"limit": 5, "used": 2, "left": 3},
            "link_x_posts": {"limit": 2, "used": 1, "left": 1},
            "way_out": None,
            "top_ups": [],
            "may_buy_top_up": False,
        }
    }


async def test_usage_without_plans_has_no_allowance(client, sells_no_plans):
    response = await client.get(USAGE)

    assert response.json() == {"allowance": None}
