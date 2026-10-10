"""Editing, rescheduling and cancelling Scheduled posts, with the frozen clock."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient

import app.api.services.scheduled_posts as scheduled_posts_service
from app.core.config import settings
from app.core.x_publisher import XAccount, XRateLimitedError
from app.publishing.publisher import run_pass

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
PUBLISHING_STARTED = "Publishing has started, so this Scheduled post can no longer change."
X_ACCOUNT_CHANGED_REASON = (
    "Not published: the X account it was for is no longer connected to Pumpkit."
)


async def _connect_x(client: AsyncClient) -> None:
    started = await client.post("/api/v1/x-connection/authorizations")
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
    completed = await client.post(
        "/api/v1/x-connection/authorizations/complete", json={"code": "c", "state": state}
    )
    assert completed.status_code == 200, completed.text


async def _schedule(client: AsyncClient, publish_at: str, text: str = "Later today.") -> dict:
    response = await client.post(SCHEDULED_POSTS, json={"text": text, "publish_at": publish_at})
    assert response.status_code == 201, response.text
    return response.json()


async def _listed(client: AsyncClient) -> list[dict]:
    return (await client.get(SCHEDULED_POSTS)).json()["data"]


async def test_editing_the_text_of_a_scheduled_post_saves_it(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    scheduled = await _schedule(client, "2026-10-10T14:00:00Z", "Lanch day.")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"text": "  Launch day.  "}
    )

    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited == {**scheduled, "text": "Launch day."}
    assert await _listed(client) == [edited]


async def test_moving_a_scheduled_post_saves_the_new_time_in_utc_and_lists_it_in_order(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    moved = await _schedule(client, "2026-10-11T09:00:00Z", "Moved")
    await _schedule(client, "2026-10-12T09:00:00Z", "Stays")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{moved['id']}", json={"publish_at": "2026-10-13T11:30:00+02:00"}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {**moved, "publish_at": "2026-10-13T09:30:00Z"}
    assert [p["text"] for p in await _listed(client)] == ["Stays", "Moved"]


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"publish_at": "2026-10-10T12:01:00Z"}, "Pick a time at least a minute from now."),
        ({"publish_at": "2027-10-10T12:01:00Z"}, "Pick a time within a year from now."),
        ({"publish_at": "2026-10-10T14:00:30Z"}, "Pick a time on a whole minute."),
        ({"text": "a" * 281}, "This post is 281 characters by X's count, over the 280 limit."),
    ],
)
async def test_an_edit_follows_the_same_time_window_and_length_rules_as_scheduling(
    client, subscribed, fake_x_publisher, fixed_clock, change, detail
):
    await _connect_x(client)
    scheduled = await _schedule(client, "2026-10-10T14:00:00Z")

    response = await client.patch(f"{SCHEDULED_POSTS}/{scheduled['id']}", json=change)

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert await _listed(client) == [scheduled]


@pytest.mark.parametrize(
    "change",
    [{}, {"text": "   "}, {"publish_at": "2026-10-10T14:00:00"}, {"state": "scheduled"}],
)
async def test_an_edit_needs_a_text_or_a_publish_time_with_a_timezone(
    client, subscribed, fake_x_publisher, fixed_clock, change
):
    await _connect_x(client)
    scheduled = await _schedule(client, "2026-10-10T14:00:00Z")

    response = await client.patch(f"{SCHEDULED_POSTS}/{scheduled['id']}", json=change)

    assert response.status_code == 422
    assert await _listed(client) == [scheduled]


async def test_a_publishing_scheduled_post_cannot_be_edited(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    scheduled = await _schedule(client, "2026-10-10T12:02:00Z", "Going out")
    fixed_clock.advance(timedelta(minutes=2))
    async with db_session_maker() as session:
        assert await scheduled_posts_service.claim(
            session, scheduled_post_id=scheduled["id"], now=fixed_clock()
        )
        await session.commit()

    edited = await client.patch(f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"text": "Changed"})
    moved = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"publish_at": "2026-10-11T09:00:00Z"}
    )

    for response in (edited, moved):
        assert response.status_code == 409
        assert response.json()["detail"] == PUBLISHING_STARTED
    assert [(p["text"], p["state"]) for p in await _listed(client)] == [("Going out", "publishing")]


async def test_a_published_scheduled_post_cannot_be_edited(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    published = (
        await client.post(SCHEDULED_POSTS, json={"text": "Out", "publish_now": True})
    ).json()

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{published['id']}",
        json={"text": "Changed", "publish_at": "2026-10-11T09:00:00Z"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == PUBLISHING_STARTED
    assert await _listed(client) == [published]


async def test_rescheduling_a_failed_post_sends_it_to_the_x_account_connected_now(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    scheduled = await _schedule(client, "2026-10-10T12:02:00Z", "For Ada")
    fake_x_publisher.account = XAccount(user_id="2002", handle="grace", subscription_type="None")
    await _connect_x(client)
    fixed_clock.advance(timedelta(minutes=2))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    assert (await _listed(client))[0]["failed_reason"] == X_ACCOUNT_CHANGED_REASON

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}",
        json={"text": "For Grace", "publish_at": "2026-10-10T12:05:00Z"},
    )

    assert response.status_code == 200, response.text
    rescheduled = response.json()
    assert rescheduled["state"] == "scheduled"
    assert rescheduled["failed_reason"] is None
    assert rescheduled["publish_at"] == "2026-10-10T12:05:00Z"
    fixed_clock.advance(timedelta(minutes=3))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    assert (await _listed(client))[0]["state"] == "published"
    assert fake_x_publisher.published == [("access-2002-2", "For Grace")]


async def test_rescheduling_a_post_waiting_to_retry_drops_its_backoff(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    scheduled = await _schedule(client, "2026-10-10T12:02:00Z", "Busy X")
    fake_x_publisher.fail_publish = XRateLimitedError("429")
    # Tried at 12:02:30 and 12:03:30; without the reset the next try would wait for 12:05:30.
    for minutes in (2, 1):
        fixed_clock.advance(timedelta(minutes=minutes))
        await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    fake_x_publisher.fail_publish = None

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"publish_at": "2026-10-10T12:05:00Z"}
    )
    fixed_clock.advance(timedelta(minutes=1, seconds=30))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert response.status_code == 200, response.text
    assert (await _listed(client))[0]["state"] == "published"
    assert len(fake_x_publisher.published) == 3


async def test_rescheduling_needs_an_x_connection(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    scheduled = await _schedule(client, "2026-10-10T14:00:00Z")
    assert (await client.delete("/api/v1/x-connection")).status_code == 204

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"publish_at": "2026-10-11T09:00:00Z"}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Connect your X account first."
    assert await _listed(client) == [scheduled]


async def test_cancelling_a_scheduled_post_removes_it(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    cancelled = await _schedule(client, "2026-10-10T12:02:00Z", "Cancelled")
    kept = await _schedule(client, "2026-10-10T12:03:00Z", "Kept")

    response = await client.delete(f"{SCHEDULED_POSTS}/{cancelled['id']}")

    assert response.status_code == 204
    assert await _listed(client) == [kept]
    fixed_clock.advance(timedelta(minutes=5))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    assert [text for _, text in fake_x_publisher.published] == ["Kept"]


async def test_a_publishing_or_published_scheduled_post_cannot_be_cancelled(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    published = (
        await client.post(SCHEDULED_POSTS, json={"text": "Out", "publish_now": True})
    ).json()
    publishing = await _schedule(client, "2026-10-10T12:02:00Z", "Going out")
    fixed_clock.advance(timedelta(minutes=2))
    async with db_session_maker() as session:
        assert await scheduled_posts_service.claim(
            session, scheduled_post_id=publishing["id"], now=fixed_clock()
        )
        await session.commit()

    for scheduled_post in (published, publishing):
        response = await client.delete(f"{SCHEDULED_POSTS}/{scheduled_post['id']}")

        assert response.status_code == 409
        assert response.json()["detail"] == PUBLISHING_STARTED
    assert len(await _listed(client)) == 2


async def test_a_failed_scheduled_post_stays_in_the_history_instead_of_being_cancelled(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect_x(client)
    fake_x_publisher.fail_publish = XRateLimitedError("429")
    failed = (await client.post(SCHEDULED_POSTS, json={"text": "Busy", "publish_now": True})).json()

    response = await client.delete(f"{SCHEDULED_POSTS}/{failed['id']}")

    assert response.status_code == 409
    assert response.json()["detail"] == "Only a Scheduled post still waiting can be cancelled."
    assert await _listed(client) == [failed]


async def test_another_user_s_scheduled_post_is_not_found(
    client, subscribed, fake_x_publisher, fixed_clock
):
    edited = await client.patch(
        f"{SCHEDULED_POSTS}/scheduled_post_01M4JS3D7BER5QZANNA2D0EFRQ", json={"text": "Mine?"}
    )
    cancelled = await client.delete(f"{SCHEDULED_POSTS}/scheduled_post_01M4JS3D7BER5QZANNA2D0EFRQ")

    assert edited.status_code == cancelled.status_code == 404


async def test_a_user_who_is_not_subscribed_cannot_edit(client, fake_x_publisher, fixed_clock):
    response = await client.patch(
        f"{SCHEDULED_POSTS}/scheduled_post_01M4JS3D7BER5QZANNA2D0EFRQ", json={"text": "Mine?"}
    )

    assert response.status_code == 403


@pytest.fixture
def cap_of_two(monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULED_POSTS_MONTHLY_CAP", 2)


OCTOBER_FULL = (
    "You have 2 Scheduled posts in October 2026, the most for one month. "
    "The cap resets on November 1, 2026."
)


async def test_rescheduling_into_a_full_month_is_refused_with_the_date_the_cap_resets(
    client, subscribed, fake_x_publisher, fixed_clock, cap_of_two
):
    await _connect_x(client)
    await _schedule(client, "2026-10-11T09:00:00Z", "First")
    await _schedule(client, "2026-10-12T09:00:00Z", "Second")
    november = await _schedule(client, "2026-11-02T09:00:00Z", "November")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{november['id']}", json={"publish_at": "2026-10-13T09:00:00Z"}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == OCTOBER_FULL
    assert [p["publish_at"] for p in await _listed(client)][-1] == "2026-11-02T09:00:00Z"


async def test_moving_a_post_within_its_full_month_is_allowed(
    client, subscribed, fake_x_publisher, fixed_clock, cap_of_two
):
    await _connect_x(client)
    await _schedule(client, "2026-10-11T09:00:00Z", "First")
    second = await _schedule(client, "2026-10-12T09:00:00Z", "Second")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{second['id']}", json={"publish_at": "2026-10-20T09:00:00Z"}
    )

    assert response.status_code == 200, response.text


async def test_cancelling_frees_a_place_in_a_full_month(
    client, subscribed, fake_x_publisher, fixed_clock, cap_of_two
):
    await _connect_x(client)
    first = await _schedule(client, "2026-10-11T09:00:00Z", "First")
    await _schedule(client, "2026-10-12T09:00:00Z", "Second")

    await client.delete(f"{SCHEDULED_POSTS}/{first['id']}")
    response = await client.post(
        SCHEDULED_POSTS, json={"text": "Third", "publish_at": "2026-10-13T09:00:00Z"}
    )

    assert response.status_code == 201, response.text
