"""
The rules every new or edited Scheduled post meets, through the mediator the web routes and the
MCP tools share. The route and tool suites keep one case of each refusal.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import update

from pumpkit.auth.models import User
from pumpkit.core.config import settings
from pumpkit.core.errors import ConflictError, NotFoundError, RefusedError
from pumpkit.posts.models import Post
from pumpkit.scheduling import mediator
from pumpkit.scheduling.communities import NOT_A_COMMUNITY
from pumpkit.scheduling.rules import (
    MonthFull,
    NewScheduledPost,
    RuleBroken,
    ScheduledPostEdit,
    ToCommunity,
    ToProfile,
)
from pumpkit.scheduling.schemas import ScheduledPostResponse
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_publisher import XAccount, XPostRejectedError
from tests.scheduling.reading import scheduled_posts_through_the_mediator

COMMUNITY_ID = "1493446837214187523"
COMMUNITY_URL = f"https://x.com/i/communities/{COMMUNITY_ID}"
OCTOBER_FULL = (
    "You have 2 X posts in October 2026, the most for one month. "
    "The cap resets on November 1, 2026."
)


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


@pytest.fixture
def create(db, user, subscribed, fake_x_publisher, fake_x_reader, fixed_clock, post_with):
    """
    A new Scheduled post for `user` for 14:00 UTC unless the fields say otherwise, copied from a
    new Post's Text of `parts` unless `post_id` names one.
    """

    async def _create(**fields) -> ScheduledPostResponse:
        if "post_id" not in fields:
            fields["post_id"] = await post_with(*fields.pop("parts", ["Shipping on Monday."]))
        if not fields.get("publish_now"):
            fields.setdefault("publish_at", _at("2026-10-10T14:00:00Z"))
        return await mediator.create_scheduled_post(
            db=db,
            publisher=fake_x_publisher,
            reader=fake_x_reader,
            user=user,
            new=NewScheduledPost(**fields),
            now=fixed_clock(),
        )

    return _create


@pytest.fixture
def edit(db, user, fake_x_publisher, fake_x_reader, fixed_clock):
    async def _edit(scheduled_post_id: str, **fields) -> ScheduledPostResponse:
        return await mediator.edit_scheduled_post(
            db=db,
            publisher=fake_x_publisher,
            reader=fake_x_reader,
            user=user,
            scheduled_post_id=scheduled_post_id,
            edit=ScheduledPostEdit(**fields),
            now=fixed_clock(),
        )

    return _edit


async def _listed(db, user) -> list[ScheduledPostResponse]:
    return await scheduled_posts_through_the_mediator(db, user)


@pytest.fixture
def cap_of_two(monkeypatch):
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 2)


@pytest.mark.parametrize(
    "fields",
    [
        {"post_id": "post_1"},
        {
            "post_id": "post_1",
            "publish_at": _at("2026-10-10T14:00:00Z"),
            "publish_now": True,
        },
    ],
)
def test_a_new_scheduled_post_has_either_a_publish_time_or_publish_now(fields):
    with pytest.raises(RuleBroken) as refused:
        NewScheduledPost(**fields)

    assert refused.value.detail == "Give either a publish time or publish now, not both."


def test_an_edit_changes_something():
    with pytest.raises(RuleBroken) as refused:
        ScheduledPostEdit()

    assert refused.value.detail == (
        "Change the text, the publish time, the community or sharing with followers."
    )


async def test_without_an_x_connection_connecting_x_is_asked_for_on_the_settings_page(
    create, fake_x_publisher
):
    with pytest.raises(ConflictError) as refused:
        await create(publish_now=True)

    assert refused.value.detail == "Connect your X account first."
    assert refused.value.fix_page == "/settings"
    assert fake_x_publisher.published == []


async def test_an_x_connection_x_no_longer_accepts_must_be_reconnected_first(
    db, user, create, connect_x
):
    await connect_x()
    await db.execute(
        update(XConnection).where(XConnection.user_id == user.id).values(needs_reconnect=True)
    )
    await db.commit()

    with pytest.raises(ConflictError) as refused:
        await create()

    assert refused.value.detail == (
        "X no longer accepts Pumpkit's access to your account. Reconnect X first."
    )
    assert refused.value.fix_page == "/settings"


async def test_rescheduling_needs_an_x_connection_but_a_new_text_does_not(
    db, user, create, edit, connect_x
):
    await connect_x()
    scheduled = await create()
    await db.execute(update(XConnection).values(needs_reconnect=True))
    await db.commit()

    edited = await edit(scheduled.id, parts=["New words."])
    with pytest.raises(ConflictError):
        await edit(scheduled.id, publish_at=_at("2026-10-11T14:00:00Z"))

    assert edited.parts[0].text == "New words."


async def test_every_part_of_the_post_s_text_is_copied(db, user, create, connect_x):
    await connect_x()
    post = Post(
        user_id=user.id,
        brief="ship",
        corpus_post_ids=[],
        created_at=_at("2026-10-01"),
        text_format="thread",
        text_parts=["The Text, Part one.", "The Text, Part two."],
        text_version_number=1,
    )
    db.add(post)
    await db.commit()

    scheduled = await create(post_id=post.id)

    assert [part.text for part in scheduled.parts] == [
        "The Text, Part one.",
        "The Text, Part two.",
    ]
    assert scheduled.post_id == post.id


async def test_another_user_s_post_is_not_found(db, user, create, connect_x):
    await connect_x()
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.flush()
    bobs_post = Post(
        user_id=bob.id,
        brief="bob's",
        corpus_post_ids=[],
        created_at=_at("2026-10-01"),
        text_format="post",
        text_parts=["Bob's words."],
        text_version_number=1,
    )
    db.add(bobs_post)
    await db.commit()

    with pytest.raises(NotFoundError) as refused:
        await create(post_id=bobs_post.id)

    assert refused.value.detail == "Post not found."
    assert await _listed(db, user) == []


async def test_a_text_over_the_limit_by_x_s_count_is_refused(create, edit, connect_x):
    await connect_x()
    scheduled = await create()
    # 276 code points, but CJK characters count two each: 281 by X's count.
    text = "a" * 270 + " 日本語のテ"

    with pytest.raises(RefusedError) as created:
        await create(parts=[text])
    with pytest.raises(RefusedError) as edited:
        await edit(scheduled.id, parts=[text])

    assert (
        created.value.detail
        == edited.value.detail
        == ("This post is 281 characters by X's count, over the 280 limit.")
    )


async def test_a_text_at_the_limit_by_x_s_count_is_accepted_however_long_its_url(create, connect_x):
    await connect_x()

    scheduled = await create(parts=["a" * 256 + " https://example.com/" + "x" * 100])

    assert scheduled.state == "scheduled"


@pytest.mark.parametrize("subscription_type", ["Premium", "PremiumPlus"])
async def test_an_x_premium_account_takes_up_to_25_000_characters_by_x_s_count(
    create, edit, fake_x_publisher, connect_x, subscription_type
):
    fake_x_publisher.account = XAccount(
        user_id="1001", handle="ada", subscription_type=subscription_type
    )
    await connect_x()
    # 25,077 code points, but the URL counts 23: 25,000 by X's count.
    at_limit = "a" * 24_976 + " https://example.com/" + "x" * 80

    scheduled = await create(parts=[at_limit])
    edited = await edit(scheduled.id, parts=["b" * 281])
    with pytest.raises(RefusedError) as refused:
        await create(parts=["a" * 24_990 + " 日本語のテ"])

    assert edited.parts[0].text == "b" * 281
    assert refused.value.detail == (
        "This post is 25,001 characters by X's count, over the 25,000 limit."
    )


# A minute and a half, and a year less half a minute, after the frozen 12:00:30.
@pytest.mark.parametrize("publish_at", ["2026-10-10T12:02:00Z", "2027-10-10T12:00:00Z"])
async def test_times_at_the_edges_of_the_window_are_accepted(create, connect_x, publish_at):
    await connect_x()

    scheduled = await create(publish_at=_at(publish_at))

    assert scheduled.publish_at == _at(publish_at)


@pytest.mark.parametrize(
    ("publish_at", "detail"),
    [
        ("2026-10-10T12:01:00Z", "Pick a time at least a minute from now."),
        ("2026-10-10T11:00:00Z", "Pick a time at least a minute from now."),
        ("2027-10-10T12:01:00Z", "Pick a time within a year from now."),
        ("2026-10-10T14:00:30Z", "Pick a time on a whole minute."),
    ],
)
async def test_times_outside_the_window_or_off_the_minute_are_refused(
    db, user, create, edit, connect_x, publish_at, detail
):
    await connect_x()
    scheduled = await create()

    with pytest.raises(RefusedError) as created:
        await create(publish_at=_at(publish_at))
    with pytest.raises(RefusedError) as moved:
        await edit(scheduled.id, publish_at=_at(publish_at))

    assert created.value.detail == moved.value.detail == detail
    assert len(await _listed(db, user)) == 1


async def test_a_full_month_is_refused_with_the_date_the_cap_resets(
    db, user, create, connect_x, fake_x_publisher, cap_of_two
):
    await connect_x()
    await create(parts=["First"], publish_at=_at("2026-10-11T09:00:00Z"))
    await create(parts=["Second"], publish_at=_at("2026-10-30T09:00:00Z"))

    with pytest.raises(MonthFull) as scheduled:
        await create(parts=["Third"], publish_at=_at("2026-10-12T09:00:00Z"))
    with pytest.raises(MonthFull) as posted_now:
        await create(publish_now=True)

    assert scheduled.value.status_code == 409
    assert scheduled.value.detail == posted_now.value.detail == OCTOBER_FULL
    assert [p.parts[0].text for p in await _listed(db, user)] == ["First", "Second"]
    assert fake_x_publisher.published == []


async def test_published_and_failed_scheduled_posts_count_towards_the_cap(
    create, connect_x, fake_x_publisher, cap_of_two
):
    await connect_x()
    published = await create(parts=["Out"], publish_now=True)
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Duplicate content.")
    failed = await create(parts=["Refused"], publish_now=True)

    with pytest.raises(MonthFull):
        await create()

    assert published.state == "published"
    assert failed.state == "failed"


async def test_a_scheduled_post_for_next_month_is_accepted_while_this_month_is_full(
    create, connect_x, cap_of_two
):
    await connect_x()
    await create(publish_at=_at("2026-10-11T09:00:00Z"))
    await create(publish_at=_at("2026-10-12T09:00:00Z"))

    scheduled = await create(publish_at=_at("2026-11-01T00:00:00Z"))

    assert scheduled.state == "scheduled"


async def test_months_are_counted_in_utc(create, connect_x, cap_of_two):
    await connect_x()
    await create(publish_at=_at("2026-10-11T09:00:00Z"))
    await create(publish_at=_at("2026-10-31T23:59:00Z"))

    # November 1 in Rome, still October 31 in UTC.
    with pytest.raises(MonthFull) as rome_november:
        await create(publish_at=_at("2026-11-01T00:30:00+01:00"))
    new_york_october = await create(publish_at=_at("2026-10-31T20:00:00-04:00"))

    assert rome_november.value.detail == OCTOBER_FULL
    assert new_york_october.publish_at == _at("2026-11-01T00:00:00Z")


async def test_a_full_december_resets_on_january_1(create, connect_x, cap_of_two):
    await connect_x()
    await create(publish_at=_at("2026-12-01T00:00:00Z"))
    await create(publish_at=_at("2026-12-31T23:59:00Z"))

    with pytest.raises(MonthFull) as refused:
        await create(publish_at=_at("2026-12-15T09:00:00Z"))

    assert refused.value.detail == (
        "You have 2 X posts in December 2026, the most for one month. "
        "The cap resets on January 1, 2027."
    )


async def test_post_now_works_again_once_the_utc_month_turns(
    create, connect_x, fixed_clock, cap_of_two
):
    await connect_x()
    await create(publish_at=_at("2026-10-11T09:00:00Z"))
    await create(publish_at=_at("2026-10-12T09:00:00Z"))
    # To 2026-10-31 23:59:30 UTC.
    fixed_clock.advance(timedelta(days=21, hours=11, minutes=59))
    with pytest.raises(MonthFull):
        await create(publish_now=True)
    fixed_clock.advance(timedelta(minutes=1))

    after = await create(publish_now=True)

    assert after.publish_at == _at("2026-11-01T00:00:00Z")
    assert after.state == "published"


async def test_rescheduling_into_a_full_month_is_refused_but_moving_within_it_is_not(
    create, edit, connect_x, cap_of_two
):
    await connect_x()
    october = await create(publish_at=_at("2026-10-11T09:00:00Z"))
    await create(publish_at=_at("2026-10-12T09:00:00Z"))
    november = await create(publish_at=_at("2026-11-02T09:00:00Z"))

    moved = await edit(october.id, publish_at=_at("2026-10-20T09:00:00Z"))
    with pytest.raises(MonthFull) as refused:
        await edit(november.id, publish_at=_at("2026-10-13T09:00:00Z"))

    assert moved.publish_at == _at("2026-10-20T09:00:00Z")
    assert refused.value.detail == OCTOBER_FULL


async def test_with_no_cap_a_month_takes_more_than_100(create, connect_x, monkeypatch):
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", None)
    await connect_x()
    for day in range(11, 31):
        for hour in range(9, 14):
            await create(publish_at=_at(f"2026-10-{day}T{hour:02}:00:00Z"))

    hundred_and_first = await create(publish_at=_at("2026-10-31T09:00:00Z"))
    posted_now = await create(publish_now=True)

    assert hundred_and_first.state == "scheduled"
    assert posted_now.state == "published"


async def test_with_a_cap_of_0_nothing_can_be_scheduled_or_posted_now(
    create, connect_x, fake_x_publisher, monkeypatch
):
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 0)
    await connect_x()

    with pytest.raises(MonthFull):
        await create()
    with pytest.raises(MonthFull):
        await create(publish_now=True)

    assert fake_x_publisher.published == []


@pytest.mark.parametrize("pasted", [COMMUNITY_URL, COMMUNITY_ID])
async def test_a_community_is_named_as_x_names_it(create, connect_x, fake_x_reader, pasted):
    await connect_x()
    fake_x_reader.communities[COMMUNITY_ID] = "Build in Public"

    scheduled = await create(community=pasted)

    assert scheduled.community is not None
    assert (scheduled.community.id, scheduled.community.name) == (COMMUNITY_ID, "Build in Public")
    assert fake_x_reader.community_calls == [COMMUNITY_ID]


@pytest.mark.parametrize("failure", ["not_configured", "fail"])
async def test_without_twitterapi_io_a_community_is_kept_without_a_name(
    create, connect_x, fake_x_reader, failure
):
    await connect_x()
    setattr(fake_x_reader, failure, True)

    scheduled = await create(community=COMMUNITY_ID)

    assert scheduled.community is not None
    assert (scheduled.community.id, scheduled.community.name) == (COMMUNITY_ID, None)


@pytest.mark.parametrize(
    "pasted", ["", "abc", "12345678901234567890", "https://x.com/levelsio", "https://x.com/i/c/1"]
)
async def test_text_that_is_not_a_community_is_refused_without_a_lookup(
    db, user, create, edit, connect_x, fake_x_reader, pasted
):
    await connect_x()
    scheduled = await create()

    with pytest.raises(RefusedError) as created:
        await create(community=pasted)
    with pytest.raises(RefusedError) as edited:
        await edit(scheduled.id, destination=ToCommunity(pasted=pasted))

    assert created.value.detail == edited.value.detail == NOT_A_COMMUNITY
    assert fake_x_reader.community_calls == []
    assert len(await _listed(db, user)) == 1


async def test_a_community_x_does_not_have_is_refused(db, user, create, edit, connect_x):
    await connect_x()
    scheduled = await create()

    with pytest.raises(NotFoundError) as created:
        await create(community=COMMUNITY_ID)
    with pytest.raises(NotFoundError) as edited:
        await edit(scheduled.id, destination=ToCommunity(pasted=COMMUNITY_ID))

    assert (
        created.value.detail
        == edited.value.detail
        == ("X has no community with that ID. Check the URL.")
    )
    assert [p.community for p in await _listed(db, user)] == [None]


@pytest.mark.parametrize(
    "fields",
    [
        {"parts": ["a" * 281]},
        {"publish_at": _at("2026-10-10T12:00:00Z")},
        {"post_id": "post_someone_else"},
    ],
)
async def test_a_request_refused_before_the_community_lookup_reads_no_x(
    create, connect_x, fake_x_reader, fields
):
    await connect_x()

    with pytest.raises((RefusedError, NotFoundError)):
        await create(community=COMMUNITY_ID, **fields)

    assert fake_x_reader.community_calls == []


async def test_without_an_x_connection_the_community_is_not_looked_up(create, fake_x_reader):
    with pytest.raises(ConflictError):
        await create(community=COMMUNITY_ID)

    assert fake_x_reader.community_calls == []


async def test_a_full_month_is_refused_before_the_community_lookup(
    create, connect_x, fake_x_reader, monkeypatch
):
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 0)
    await connect_x()

    with pytest.raises(MonthFull):
        await create(community=COMMUNITY_ID)

    assert fake_x_reader.community_calls == []


async def test_sharing_with_followers_without_a_community_is_ignored(create, edit, connect_x):
    await connect_x()

    scheduled = await create(share_with_followers=True)
    edited = await edit(scheduled.id, share_with_followers=True)

    assert scheduled.community is None
    assert scheduled.share_with_followers is False
    assert edited.share_with_followers is False


async def test_an_edit_keeps_the_destination_it_does_not_change(
    create, edit, connect_x, fake_x_reader
):
    await connect_x()
    fake_x_reader.communities[COMMUNITY_ID] = "Build in Public"
    scheduled = await create(community=COMMUNITY_ID, share_with_followers=True)

    retimed = await edit(scheduled.id, publish_at=_at("2026-10-11T14:00:00Z"))
    unshared = await edit(scheduled.id, share_with_followers=False)
    to_profile = await edit(scheduled.id, destination=ToProfile())

    assert retimed.community == scheduled.community
    assert retimed.share_with_followers is True
    assert unshared.community == scheduled.community
    assert unshared.share_with_followers is False
    assert to_profile.community is None
    assert fake_x_reader.community_calls == [COMMUNITY_ID]
