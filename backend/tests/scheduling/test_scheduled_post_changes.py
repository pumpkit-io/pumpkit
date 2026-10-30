"""Editing, rescheduling and cancelling Scheduled posts, with the frozen clock."""

from datetime import timedelta

import pytest
from httpx import AsyncClient

import pumpkit.scheduling.service as scheduled_posts_service
from pumpkit.core.config import settings
from pumpkit.scheduling.publisher import run_pass
from pumpkit.x_connection.x_publisher import XAccount, XPostRejectedError, XRateLimitedError
from tests.scheduling.reading import scheduled_posts

SCHEDULED_POSTS = "/api/v1/scheduled-posts"
PUBLISHING_STARTED = "Publishing has started, so this scheduled post can no longer change."
X_ACCOUNT_CHANGED_REASON = (
    "Not published: the X account it was for is no longer connected to Pumpkit."
)


async def _schedule(
    client: AsyncClient, post_with, publish_at: str, text: str = "Later today."
) -> dict:
    response = await client.post(
        SCHEDULED_POSTS,
        json={"post_id": await post_with(text), "publish_at": publish_at},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _listed(client: AsyncClient) -> list[dict]:
    return await scheduled_posts(client)


async def test_editing_the_text_of_a_scheduled_post_saves_it(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    scheduled = await _schedule(client, post_with, "2026-10-10T14:00:00Z", "Lanch day.")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"parts": ["  Launch day.  "]}
    )

    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited == {
        **scheduled,
        "parts": [{"text": "Launch day.", "live": False, "x_post_url": None}],
    }
    assert await _listed(client) == [edited]


async def test_editing_the_parts_of_a_scheduled_post_replaces_them_all_in_order(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    scheduled = await _schedule(client, post_with, "2026-10-10T14:00:00Z", "One post.")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"parts": ["Now two.", "The second."]}
    )
    shortened = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"parts": ["Back to one."]}
    )

    assert [part["text"] for part in response.json()["parts"]] == ["Now two.", "The second."]
    assert shortened.json()["parts"] == [
        {"text": "Back to one.", "live": False, "x_post_url": None}
    ]
    assert await _listed(client) == [shortened.json()]


async def _failed_after_part_one(
    client: AsyncClient,
    post_with,
    fake_x_publisher,
    parts: tuple[str, ...] = ("Live one.", "Refused two."),
) -> dict:
    """A Thread whose Part 1 is live and whose Part 2 X refused."""
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = 2
    response = await client.post(
        SCHEDULED_POSTS,
        json={"post_id": await post_with(*list(parts)), "publish_now": True},
    )
    assert response.json()["state"] == "failed", response.text
    fake_x_publisher.fail_publish = None
    return response.json()


LIVE_PART_LOCKED = "Part 1 is already on X, so it can't change."


@pytest.mark.parametrize(
    "parts",
    [
        pytest.param(["Changed one.", "Fixed two."], id="changed"),
        pytest.param(["Fixed two."], id="removed"),
        pytest.param(["Refused two.", "Live one."], id="moved"),
        pytest.param(["New first.", "Live one.", "Refused two."], id="pushed back"),
    ],
)
async def test_a_live_part_of_a_failed_thread_cannot_change(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, parts, post_with
):
    await connect_x()
    failed = await _failed_after_part_one(client, post_with, fake_x_publisher)

    response = await client.patch(f"{SCHEDULED_POSTS}/{failed['id']}", json={"parts": parts})

    assert response.status_code == 409
    assert response.json()["detail"] == LIVE_PART_LOCKED
    assert await _listed(client) == [failed]


async def test_a_failed_thread_cannot_be_cut_down_to_its_live_parts(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    failed = await _failed_after_part_one(client, post_with, fake_x_publisher)

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"parts": ["Live one."], "publish_at": "2026-10-10T13:00:00Z"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Keep at least one part after the ones already on X."
    assert await _listed(client) == [failed]


async def test_the_parts_after_the_live_ones_can_be_edited_added_removed_and_reordered(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    failed = await _failed_after_part_one(
        client, post_with, fake_x_publisher, ("Live one.", "Refused two.", "Three.", "Four.")
    )

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"parts": ["Live one.", "Four.", "Fixed two.", "New five."]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["parts"] == [
        failed["parts"][0],
        {"text": "Four.", "live": False, "x_post_url": None},
        {"text": "Fixed two.", "live": False, "x_post_url": None},
        {"text": "New five.", "live": False, "x_post_url": None},
    ]
    assert failed["parts"][0]["live"] is True
    assert await _listed(client) == [response.json()]


async def test_rescheduling_a_thread_failed_partway_publishes_only_the_parts_not_live(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    failed = await _failed_after_part_one(
        client, post_with, fake_x_publisher, ("Live one.", "Refused two.", "Three.")
    )
    await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}",
        json={"parts": ["Live one.", "Fixed two.", "Three."], "publish_at": "2026-10-10T13:00:00Z"},
    )
    fixed_clock.advance(timedelta(hours=1))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    [published] = await _listed(client)
    assert published["state"] == "published"
    assert [text for _, text in fake_x_publisher.published[2:]] == ["Fixed two.", "Three."]
    assert fake_x_publisher.replied_to[2:] == ["1890000000000000001", "1890000000000000003"]
    assert published["x_post_url"] == "https://x.com/i/web/status/1890000000000000001"


async def test_rescheduling_a_thread_that_failed_on_part_1_publishes_it_from_the_start(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    failed = (
        await client.post(
            SCHEDULED_POSTS,
            json={"post_id": await post_with("One.", "Two."), "publish_now": True},
        )
    ).json()
    assert failed["state"] == "failed"
    fake_x_publisher.fail_publish = None
    await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}", json={"publish_at": "2026-10-10T13:00:00Z"}
    )
    fixed_clock.advance(timedelta(hours=1))

    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)

    assert [text for _, text in fake_x_publisher.published[1:]] == ["One.", "Two."]
    assert fake_x_publisher.replied_to[1:] == [None, "1890000000000000002"]
    assert (await _listed(client))[0]["state"] == "published"


async def test_an_edited_part_over_the_limit_is_refused_naming_the_part(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    scheduled = await _schedule(client, post_with, "2026-10-10T14:00:00Z", "Stays as it is.")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}",
        json={"parts": ["Fine.", "Fine too.", "a" * 281]},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Part 3 is 281 characters by X's count, over the 280 limit."
    )
    assert await _listed(client) == [scheduled]


async def test_moving_a_scheduled_post_saves_the_new_time_in_utc_and_lists_it_in_order(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    moved = await _schedule(client, post_with, "2026-10-11T09:00:00Z", "Moved")
    await _schedule(client, post_with, "2026-10-12T09:00:00Z", "Stays")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{moved['id']}", json={"publish_at": "2026-10-13T11:30:00+02:00"}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {**moved, "publish_at": "2026-10-13T09:30:00Z"}
    assert [p["parts"][0]["text"] for p in await _listed(client)] == ["Stays", "Moved"]


@pytest.mark.parametrize(
    "change",
    [{}, {"parts": ["   "]}, {"publish_at": "2026-10-10T14:00:00"}, {"state": "scheduled"}],
)
async def test_an_edit_needs_a_text_or_a_publish_time_with_a_timezone(
    client, subscribed, fake_x_publisher, fixed_clock, change, connect_x, post_with
):
    await connect_x()
    scheduled = await _schedule(client, post_with, "2026-10-10T14:00:00Z")

    response = await client.patch(f"{SCHEDULED_POSTS}/{scheduled['id']}", json=change)

    assert response.status_code == 422
    assert await _listed(client) == [scheduled]


async def test_a_publishing_scheduled_post_cannot_be_edited(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    scheduled = await _schedule(client, post_with, "2026-10-10T12:02:00Z", "Going out")
    fixed_clock.advance(timedelta(minutes=2))
    async with db_session_maker() as session:
        assert await scheduled_posts_service.claim(
            session, scheduled_post_id=scheduled["id"], now=fixed_clock()
        )
        await session.commit()

    edited = await client.patch(f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"parts": ["Changed"]})
    moved = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"publish_at": "2026-10-11T09:00:00Z"}
    )

    for response in (edited, moved):
        assert response.status_code == 409
        assert response.json()["detail"] == PUBLISHING_STARTED
    assert [(p["parts"][0]["text"], p["state"]) for p in await _listed(client)] == [
        ("Going out", "publishing")
    ]


async def test_a_published_scheduled_post_cannot_be_edited(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    published = (
        await client.post(
            SCHEDULED_POSTS,
            json={"post_id": await post_with("Out"), "publish_now": True},
        )
    ).json()

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{published['id']}",
        json={"parts": ["Changed"], "publish_at": "2026-10-11T09:00:00Z"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == PUBLISHING_STARTED
    assert await _listed(client) == [published]


async def test_rescheduling_a_failed_post_sends_it_to_the_x_account_connected_now(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    scheduled = await _schedule(client, post_with, "2026-10-10T12:02:00Z", "For Ada")
    fake_x_publisher.account = XAccount(user_id="2002", handle="grace", subscription_type="None")
    await connect_x()
    fixed_clock.advance(timedelta(minutes=2))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    assert (await _listed(client))[0]["failed_reason"] == X_ACCOUNT_CHANGED_REASON

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}",
        json={"parts": ["For Grace"], "publish_at": "2026-10-10T12:05:00Z"},
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
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    scheduled = await _schedule(client, post_with, "2026-10-10T12:02:00Z", "Busy X")
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


async def test_cancelling_a_scheduled_post_removes_it(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    cancelled = await _schedule(client, post_with, "2026-10-10T12:02:00Z", "Cancelled")
    kept = await _schedule(client, post_with, "2026-10-10T12:03:00Z", "Kept")

    response = await client.delete(f"{SCHEDULED_POSTS}/{cancelled['id']}")

    assert response.status_code == 204
    assert await _listed(client) == [kept]
    fixed_clock.advance(timedelta(minutes=5))
    await run_pass(db_session_maker, fake_x_publisher, fixed_clock)
    assert [text for _, text in fake_x_publisher.published] == ["Kept"]


async def test_a_publishing_or_published_scheduled_post_cannot_be_cancelled(
    client, db_session_maker, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    published = (
        await client.post(
            SCHEDULED_POSTS,
            json={"post_id": await post_with("Out"), "publish_now": True},
        )
    ).json()
    publishing = await _schedule(client, post_with, "2026-10-10T12:02:00Z", "Going out")
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


async def test_a_failed_scheduled_post_can_be_removed(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Duplicate content.")
    failed = (
        await client.post(
            SCHEDULED_POSTS,
            json={"post_id": await post_with("Dup"), "publish_now": True},
        )
    ).json()
    assert failed["state"] == "failed"

    response = await client.delete(f"{SCHEDULED_POSTS}/{failed['id']}")

    assert response.status_code == 204
    assert await _listed(client) == []


async def test_another_user_s_scheduled_post_is_not_found(
    client, subscribed, fake_x_publisher, fixed_clock
):
    edited = await client.patch(
        f"{SCHEDULED_POSTS}/scheduled_post_01M4JS3D7BER5QZANNA2D0EFRQ", json={"parts": ["Mine?"]}
    )
    cancelled = await client.delete(f"{SCHEDULED_POSTS}/scheduled_post_01M4JS3D7BER5QZANNA2D0EFRQ")

    assert edited.status_code == cancelled.status_code == 404


async def test_a_user_who_is_not_subscribed_cannot_edit(client, fake_x_publisher, fixed_clock):
    response = await client.patch(
        f"{SCHEDULED_POSTS}/scheduled_post_01M4JS3D7BER5QZANNA2D0EFRQ", json={"parts": ["Mine?"]}
    )

    assert response.status_code == 403


@pytest.fixture
def cap_of_two(monkeypatch):
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 2)


OCTOBER_FULL = (
    "You have 2 X posts in October 2026, the most for one month. "
    "The cap resets on November 1, 2026."
)


async def test_adding_parts_that_would_cross_the_monthly_cap_is_refused(
    client, subscribed, fake_x_publisher, fixed_clock, cap_of_two, connect_x, post_with
):
    await connect_x()
    scheduled = await _schedule(client, post_with, "2026-10-11T09:00:00Z", "One")
    await _schedule(client, post_with, "2026-10-12T09:00:00Z", "Other")

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"parts": ["One", "Two"]}
    )
    rewritten = await client.patch(f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"parts": ["Uno"]})

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "These 2 Parts would take you over the cap of 2 X posts in October 2026: you have "
        "1 already. The cap resets on November 1, 2026."
    )
    assert rewritten.status_code == 200, rewritten.text


async def test_cancelling_frees_a_place_in_a_full_month(
    client, subscribed, fake_x_publisher, fixed_clock, cap_of_two, connect_x, post_with
):
    await connect_x()
    first = await _schedule(client, post_with, "2026-10-11T09:00:00Z", "First")
    await _schedule(client, post_with, "2026-10-12T09:00:00Z", "Second")

    await client.delete(f"{SCHEDULED_POSTS}/{first['id']}")
    response = await client.post(
        SCHEDULED_POSTS,
        json={"post_id": await post_with("Third"), "publish_at": "2026-10-13T09:00:00Z"},
    )

    assert response.status_code == 201, response.text
