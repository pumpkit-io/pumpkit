"""The Scheduled post MCP tools, refusing what the web routes refuse, in the same words."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

import pumpkit.scheduling.service as scheduled_posts_service
from pumpkit.auth.models import User
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.billing.models import Subscription
from pumpkit.core.config import settings
from pumpkit.posts.models import ATTEMPT_SUCCEEDED, Post, VersionAttempt
from pumpkit.scheduling.models import SCHEDULED, ScheduledPost, ScheduledPostPart
from pumpkit.x_connection.x_publisher import (
    XNotReceivedError,
    XPostRejectedError,
    XRateLimitedError,
)
from tests.mcp_client import error_text
from tests.posts.writing_replies import written, written_thread
from tests.scheduling.reading import scheduled_posts_through_mcp

POSTS_PAGE = "http://localhost:5173/posts"
SETTINGS_PAGE = "http://localhost:5173/settings"


@pytest.fixture
async def connected(subscribed, fixed_clock, connect_x) -> None:
    await connect_x()


@pytest.fixture
async def version(client, subscribed, fake_x_reader, fake_llm) -> dict:
    """The first Version of a new Post, whose text is "The final, version one."."""
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    added = await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    assert added.status_code == 201, added.text
    fake_llm.replies = [written("sketch one"), {"post": "The final, version one."}]
    started = await client.post("/api/v1/posts", json={"brief": "ship small things"})
    assert started.status_code == 201, started.text
    post = started.json()
    return {"post_id": post["id"], **post["versions"][0]}


async def test_scheduling_a_version_answers_with_the_scheduled_page_link(
    connected, mcp, version_of, fixed_clock
):
    version_id = await version_of("Shipping on Monday.")

    result = await mcp.call_tool(
        "schedule_post", version_id=version_id, publish_at="2026-10-10T16:00:00+02:00"
    )

    assert result["isError"] is False, result
    scheduled = result["structuredContent"]
    assert scheduled["parts"][0]["text"] == "Shipping on Monday."
    assert scheduled["state"] == "scheduled"
    assert scheduled["publish_at"] == "2026-10-10T14:00:00Z"
    assert scheduled["source_version_id"] == version_id
    assert scheduled["community"] is None
    assert scheduled["post_url"] == f"{POSTS_PAGE}/{scheduled['post_id']}"
    assert await scheduled_posts_through_mcp(mcp) == [
        {key: value for key, value in scheduled.items() if key != "post_url"}
    ]


THREAD_FINAL = ["Ship small every week.", "It's how you learn.", "Start today."]


@pytest.fixture
async def thread_version(client, subscribed, fake_x_reader, fake_llm) -> dict:
    """The first Version of a new Post started as a Thread, its text the three THREAD_FINAL Parts."""
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    added = await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    assert added.status_code == 201, added.text
    fake_llm.replies = [written_thread(["one", "two", "three"]), {"parts": THREAD_FINAL}]
    started = await client.post(
        "/api/v1/posts", json={"brief": "ship small things", "format": "thread"}
    )
    assert started.status_code == 201, started.text
    return started.json()["versions"][0]


async def test_scheduling_a_thread_answers_with_each_part_in_order_and_none_live(
    connected, mcp, version_of, fixed_clock
):
    result = await mcp.call_tool(
        "schedule_post",
        version_id=await version_of("The first Part.", "The second Part."),
        publish_at="2026-10-10T14:00:00Z",
    )

    assert result["isError"] is False, result
    assert result["structuredContent"]["parts"] == [
        {"text": "The first Part.", "live": False, "x_post_url": None},
        {"text": "The second Part.", "live": False, "x_post_url": None},
    ]


async def test_post_now_on_a_thread_publishes_its_parts_as_a_chain(
    connected, mcp, version_of, fake_x_publisher, fixed_clock
):
    result = await mcp.call_tool(
        "post_now", version_id=await version_of("Thread start.", "Thread end.")
    )

    assert result["isError"] is False, result
    published = result["structuredContent"]
    assert published["state"] == "published"
    assert published["x_post_url"] == "https://x.com/i/web/status/1890000000000000001"
    assert [part["live"] for part in published["parts"]] == [True, True]
    assert fake_x_publisher.replied_to == [None, "1890000000000000001"]


async def test_editing_replaces_the_parts_and_refuses_one_over_the_limit_by_name(
    connected, mcp, fixed_clock, version_of
):
    scheduled = (await _schedule(mcp, version_of))["structuredContent"]

    edited = await mcp.call_tool(
        "edit_scheduled_post",
        scheduled_post_id=scheduled["id"],
        parts=["New first.", "New second."],
    )
    refused = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=scheduled["id"], parts=["x" * 281, "Fine."]
    )

    assert [part["text"] for part in edited["structuredContent"]["parts"]] == [
        "New first.",
        "New second.",
    ]
    assert error_text(refused) == "Part 1 is 281 characters by X's count, over the 280 limit."


async def test_scheduling_a_version_copies_its_final_and_records_the_version(
    connected, version, mcp, fixed_clock
):
    result = await mcp.call_tool(
        "schedule_post", version_id=version["id"], publish_at="2026-10-10T14:00:00Z"
    )

    assert result["isError"] is False, result
    assert result["structuredContent"]["parts"][0]["text"] == "The final, version one."
    assert result["structuredContent"]["source_version_id"] == version["id"]


async def _schedule(
    mcp, version_of, text: str = "Shipping on Monday.", at: str = "2026-10-10T14:00:00Z"
):
    """Schedule the one Version of a new Post whose text is `text`."""
    return await mcp.call_tool("schedule_post", version_id=await version_of(text), publish_at=at)


async def test_scheduling_without_an_x_connection_links_to_the_settings_page(
    subscribed, mcp, fixed_clock, version_of
):
    result = await _schedule(mcp, version_of)

    assert error_text(result) == f"Connect your X account first. {SETTINGS_PAGE}"


async def test_a_post_over_the_x_accounts_limit_is_refused(connected, mcp, fixed_clock, version_of):
    result = await _schedule(mcp, version_of, text="x" * 281)

    assert error_text(result) == "This post is 281 characters by X's count, over the 280 limit."


async def test_a_time_without_its_utc_offset_is_refused(connected, mcp, fixed_clock, version_of):
    result = await _schedule(mcp, version_of, at="2026-10-10T14:00:00")

    assert error_text(result) == "Input should have timezone info"


async def test_the_monthly_cap_counts_scheduled_posts_from_the_web_app_too(
    connected, client, mcp, fixed_clock, monkeypatch, version_of
):
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 2)
    from_web = await client.post(
        "/api/v1/scheduled-posts",
        json={"source_version_id": await version_of("First"), "publish_at": "2026-10-11T09:00:00Z"},
    )
    assert from_web.status_code == 201, from_web.text
    await _schedule(mcp, version_of, text="Second", at="2026-10-30T09:00:00Z")

    result = await _schedule(mcp, version_of, text="Third", at="2026-10-12T09:00:00Z")

    assert error_text(result) == (
        "You have 2 X posts in October 2026, the most for one month. "
        "The cap resets on November 1, 2026."
    )


COMMUNITY_ID = "1493446837214187523"
COMMUNITY_URL = f"https://x.com/i/communities/{COMMUNITY_ID}"


@pytest.fixture
def known_community(fake_x_reader) -> None:
    fake_x_reader.communities[COMMUNITY_ID] = "Build in Public"


COMMUNITY = {"id": COMMUNITY_ID, "name": "Build in Public", "url": COMMUNITY_URL}


@pytest.mark.parametrize("share_with_followers", [True, False])
async def test_scheduling_into_a_community_names_it_as_x_does(
    connected, known_community, mcp, fixed_clock, share_with_followers, version_of
):
    result = await mcp.call_tool(
        "schedule_post",
        version_id=await version_of("Shipping on Monday."),
        publish_at="2026-10-10T14:00:00Z",
        community=f"{COMMUNITY_URL}?s=20",
        share_with_followers=share_with_followers,
    )

    assert result["isError"] is False, result
    assert result["structuredContent"]["community"] == COMMUNITY
    assert result["structuredContent"]["share_with_followers"] is share_with_followers


async def test_a_community_x_doesnt_know_is_refused(connected, mcp, fixed_clock, version_of):
    result = await mcp.call_tool(
        "schedule_post",
        version_id=await version_of("Hi."),
        publish_at="2026-10-10T14:00:00Z",
        community="123",
    )

    assert error_text(result) == "X has no Community with that ID. Check the URL."
    assert (await scheduled_posts_through_mcp(mcp)) == []


async def _post_now_on_the_web(client: AsyncClient, version_id: str) -> dict:
    response = await client.post(
        "/api/v1/scheduled-posts", json={"source_version_id": version_id, "publish_now": True}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def failed(connected, client, version_of, fake_x_publisher, fixed_clock) -> dict:
    """A Scheduled post X refused when the User Posted it now in the web app."""
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Duplicate content.")
    failed = await _post_now_on_the_web(client, await version_of("Duplicate."))
    fake_x_publisher.fail_publish = None
    assert failed["state"] == "failed"
    return failed


async def test_listing_failed_posts_says_why_each_failed(failed, mcp, fixed_clock):
    listed = await mcp.call_tool("list_posts", status="failed")

    [post] = listed["structuredContent"]["data"]
    assert post["scheduled_post"]["state"] == "failed"
    assert post["scheduled_post"]["failed_reason"] == "X refused the post: Duplicate content."


async def test_editing_the_text_and_time_of_a_waiting_scheduled_post_saves_both(
    connected, mcp, fixed_clock, version_of
):
    scheduled = (await _schedule(mcp, version_of, text="Lanch day."))["structuredContent"]

    result = await mcp.call_tool(
        "edit_scheduled_post",
        scheduled_post_id=scheduled["id"],
        parts=["  Launch day.  "],
        publish_at="2026-10-11T11:30:00+02:00",
    )

    assert result["isError"] is False, result
    assert result["structuredContent"] == {
        **scheduled,
        "parts": [{"text": "Launch day.", "live": False, "x_post_url": None}],
        "publish_at": "2026-10-11T09:30:00Z",
    }


async def test_rescheduling_a_failed_scheduled_post_waits_to_publish_again(
    failed, mcp, fixed_clock
):
    result = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=failed["id"], publish_at="2026-10-10T14:00:00Z"
    )

    assert result["isError"] is False, result
    assert result["structuredContent"]["state"] == "scheduled"
    assert result["structuredContent"]["failed_reason"] is None


async def test_editing_can_move_a_scheduled_post_into_a_community_and_back_to_the_profile(
    connected, known_community, mcp, fixed_clock, version_of
):
    scheduled = (await _schedule(mcp, version_of))["structuredContent"]

    into = await mcp.call_tool(
        "edit_scheduled_post",
        scheduled_post_id=scheduled["id"],
        community=COMMUNITY_ID,
        share_with_followers=True,
    )
    assert into["structuredContent"]["community"] == COMMUNITY
    assert into["structuredContent"]["share_with_followers"] is True

    back = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=scheduled["id"], to_profile=True
    )
    assert back["isError"] is False, back
    assert back["structuredContent"]["community"] is None


async def test_editing_to_a_community_and_the_profile_at_once_is_refused(
    connected, mcp, fixed_clock, version_of
):
    scheduled = (await _schedule(mcp, version_of))["structuredContent"]

    result = await mcp.call_tool(
        "edit_scheduled_post",
        scheduled_post_id=scheduled["id"],
        community=COMMUNITY_ID,
        to_profile=True,
    )

    assert error_text(result) == "Give either a Community or the profile, not both."


async def test_editing_a_thread_failed_partway_keeps_its_live_part_locked(
    connected, mcp, fake_x_publisher, fixed_clock, version_of
):
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = 2
    failed = (
        await mcp.call_tool("post_now", version_id=await version_of("Live one.", "Refused two."))
    )["structuredContent"]
    assert failed["failed_reason"] == "X refused Part 2: Nope"

    changed = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=failed["id"], parts=["Changed.", "Fixed two."]
    )
    cut = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=failed["id"], parts=["Live one."]
    )
    fixed = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=failed["id"], parts=["Live one.", "Fixed two."]
    )

    assert error_text(changed) == "Part 1 is already on X, so it can't change."
    assert error_text(cut) == "Keep at least one Part after the ones already on X."
    assert fixed["isError"] is False, fixed
    assert [(p["text"], p["live"]) for p in fixed["structuredContent"]["parts"]] == [
        ("Live one.", True),
        ("Fixed two.", False),
    ]
    listed = await scheduled_posts_through_mcp(mcp)
    assert [p["live"] for p in listed[0]["parts"]] == [True, False]


async def test_a_thread_failed_partway_is_rescheduled_with_a_version_of_its_post(
    connected, mcp, fake_x_publisher, fixed_clock, version_of, next_version
):
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = 2
    first = await version_of("Live one.", "Refused two.")
    failed = (await mcp.call_tool("post_now", version_id=first))["structuredContent"]
    fake_x_publisher.fail_publish = None
    latest = await next_version(first, "Rewritten one.", "Fixed two.", "New three.")

    rescheduled = await mcp.call_tool(
        "edit_scheduled_post",
        scheduled_post_id=failed["id"],
        version_id=latest,
        publish_at="2026-10-10T14:00:00Z",
    )

    assert rescheduled["isError"] is False, rescheduled
    answer = rescheduled["structuredContent"]
    assert answer["state"] == "scheduled"
    assert answer["source_version_id"] == latest
    assert [(p["text"], p["live"]) for p in answer["parts"]] == [
        ("Live one.", True),
        ("Fixed two.", False),
        ("New three.", False),
    ]


async def test_editing_with_a_version_of_another_post_or_with_parts_too_is_refused(
    connected, mcp, version_of
):
    scheduled = (await _schedule(mcp, version_of))["structuredContent"]
    elsewhere = await version_of("Another Post.")

    other_post = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=scheduled["id"], version_id=elsewhere
    )
    both = await mcp.call_tool(
        "edit_scheduled_post",
        scheduled_post_id=scheduled["id"],
        version_id=scheduled["source_version_id"],
        parts=["Typed."],
    )

    assert error_text(other_post) == "Choose a Version of this Post."
    assert error_text(both) == "Give either the Parts or a Version, not both."


PUBLISHING_STARTED = "Publishing has started, so this Scheduled post can no longer change."


async def test_a_published_scheduled_post_can_be_neither_edited_nor_deleted(
    connected, client, mcp, fixed_clock, version_of
):
    published = await _post_now_on_the_web(client, await version_of("Out now."))

    edited = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=published["id"], parts=["Changed"]
    )
    deleted = await mcp.call_tool("delete_scheduled_post", scheduled_post_id=published["id"])

    assert error_text(edited) == error_text(deleted) == PUBLISHING_STARTED


async def test_a_scheduled_post_being_published_can_be_neither_edited_nor_deleted(
    connected, mcp, db_session_maker, fixed_clock, version_of
):
    scheduled = (await _schedule(mcp, version_of, at="2026-10-10T12:02:00Z"))["structuredContent"]
    fixed_clock.advance(timedelta(minutes=2))
    async with db_session_maker() as session:
        assert await scheduled_posts_service.claim(
            session, scheduled_post_id=scheduled["id"], now=fixed_clock()
        )
        await session.commit()

    edited = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=scheduled["id"], parts=["Changed"]
    )
    deleted = await mcp.call_tool("delete_scheduled_post", scheduled_post_id=scheduled["id"])

    assert error_text(edited) == error_text(deleted) == PUBLISHING_STARTED
    assert [
        (post["parts"][0]["text"], post["state"]) for post in await scheduled_posts_through_mcp(mcp)
    ] == [("Shipping on Monday.", "publishing")]


async def test_another_users_scheduled_post_is_not_found(connected, mcp, db, fixed_clock):
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.flush()
    bobs_post = Post(user_id=bob.id, brief="Bob's", corpus_post_ids=[], created_at=fixed_clock())
    bobs_version = VersionAttempt(
        post=bobs_post,
        sequence=1,
        format="post",
        status=ATTEMPT_SUCCEEDED,
        version_number=1,
        parts=["Bob's."],
        slop_tells=[],
        created_at=fixed_clock(),
    )
    db.add_all([bobs_post, bobs_version])
    await db.flush()
    bobs = ScheduledPost(
        user_id=bob.id,
        post_id=bobs_post.id,
        source_version_id=bobs_version.id,
        x_user_id="2002",
        parts=[ScheduledPostPart(position=0, text="Bob's.")],
        publish_at=fixed_clock() + timedelta(hours=2),
        state=SCHEDULED,
        created_at=fixed_clock(),
        updated_at=fixed_clock(),
    )
    db.add(bobs)
    await db.commit()

    edited = await mcp.call_tool("edit_scheduled_post", scheduled_post_id=bobs.id, parts=["Mine?"])
    deleted = await mcp.call_tool("delete_scheduled_post", scheduled_post_id=bobs.id)

    assert error_text(edited) == error_text(deleted) == "Scheduled post not found."


async def test_deleting_a_waiting_scheduled_post_takes_it_off_the_list(
    connected, mcp, fixed_clock, version_of
):
    scheduled = (await _schedule(mcp, version_of))["structuredContent"]

    result = await mcp.call_tool("delete_scheduled_post", scheduled_post_id=scheduled["id"])

    assert result["structuredContent"] == {
        "message": "The Scheduled post is deleted.",
        "post_url": f"{POSTS_PAGE}/{scheduled['post_id']}",
    }
    assert (await scheduled_posts_through_mcp(mcp)) == []


async def test_deleting_a_failed_scheduled_post_takes_it_off_the_list(failed, mcp, fixed_clock):
    result = await mcp.call_tool("delete_scheduled_post", scheduled_post_id=failed["id"])

    assert result["isError"] is False, result
    assert (await scheduled_posts_through_mcp(mcp)) == []


async def test_past_communities_are_the_ones_the_user_posted_to_before(
    connected, known_community, mcp, fixed_clock, version_of
):
    assert (await mcp.call_tool("list_past_communities"))["structuredContent"] == {"data": []}
    await mcp.call_tool(
        "schedule_post",
        version_id=await version_of("Hi."),
        publish_at="2026-10-10T14:00:00Z",
        community=COMMUNITY_ID,
    )

    result = await mcp.call_tool("list_past_communities")

    assert result["structuredContent"] == {"data": [COMMUNITY]}


async def test_tools_list_shows_post_now_and_deleting_a_scheduled_post_as_destructive(
    subscribed, mcp
):
    tools = await mcp.list_tools()

    for name in ("post_now", "delete_scheduled_post"):
        assert tools[name]["annotations"]["destructiveHint"] is True
    for name in ("schedule_post", "edit_scheduled_post"):
        assert tools[name]["annotations"] == {"readOnlyHint": False, "destructiveHint": False}
    for name in ("list_past_communities", "connect_x"):
        assert tools[name]["annotations"]["readOnlyHint"] is True


async def test_connect_x_links_to_the_settings_page(subscribed, mcp):
    result = await mcp.call_tool("connect_x")

    assert result["isError"] is False, result
    assert result["structuredContent"]["url"] == SETTINGS_PAGE
    assert SETTINGS_PAGE in result["structuredContent"]["message"]


@pytest.mark.parametrize(
    "name", ["schedule_post", "post_now", "edit_scheduled_post", "delete_scheduled_post"]
)
async def test_the_write_tools_allow_10_calls_a_minute(connected, mcp, fixed_clock, name):
    arguments = {
        "schedule_post": {"version_id": "version_missing", "publish_at": "2026-10-10T14:00:00Z"},
        "post_now": {"version_id": "version_missing"},
        "edit_scheduled_post": {"scheduled_post_id": "scheduled_post_missing", "parts": ["Hi."]},
        "delete_scheduled_post": {"scheduled_post_id": "scheduled_post_missing"},
    }[name]
    for _ in range(10):
        assert "retry_at" not in (
            (await mcp.call_tool(name, **arguments)).get("structuredContent") or {}
        )

    result = await mcp.call_tool(name, **arguments)

    assert error_text(result).startswith(f"You've called {name} too often.")
    assert result["structuredContent"]["retry_at"].endswith("Z")


@pytest.mark.parametrize("name", ["list_past_communities", "connect_x"])
async def test_the_read_only_and_link_tools_allow_60_calls_a_minute(subscribed, mcp, name):
    for _ in range(60):
        assert (await mcp.call_tool(name))["isError"] is False

    result = await mcp.call_tool(name)

    assert "retry_at" in result["structuredContent"]


@pytest.fixture
async def subscription_ended(connected, mcp, db) -> None:
    """Ends the Subscription after `user` connected X and created the API key."""
    await db.execute(delete(Subscription))
    await db.commit()


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("schedule_post", {"version_id": "version_missing", "publish_at": "2026-10-10T14:00:00Z"}),
        ("post_now", {"version_id": "version_missing"}),
        ("list_posts", {}),
        ("edit_scheduled_post", {"scheduled_post_id": "scheduled_post_missing", "parts": ["Hi."]}),
        ("delete_scheduled_post", {"scheduled_post_id": "scheduled_post_missing"}),
        ("list_past_communities", {}),
    ],
)
async def test_a_user_whose_subscription_ended_gets_the_subscribe_link(
    subscription_ended, mcp, fixed_clock, name, arguments
):
    result = await mcp.call_tool(name, **arguments)

    assert error_text(result) == (
        "This needs a Subscription. Subscribe to continue. http://localhost:5173/billing"
    )


async def test_connect_x_works_for_a_user_whose_subscription_ended(subscription_ended, mcp):
    result = await mcp.call_tool("connect_x")

    assert result["structuredContent"]["url"] == SETTINGS_PAGE


async def test_every_user_schedules_on_an_instance_that_sells_no_plans(
    sells_no_plans, client, fake_x_publisher, mcp, fixed_clock, connect_x, version_of
):
    await connect_x()

    result = await _schedule(mcp, version_of)

    assert result["isError"] is False, result


FIRST_X_POST = "https://x.com/i/web/status/1890000000000000001"


async def test_post_now_publishes_a_version_and_links_to_it_on_x(
    connected, mcp, version_of, fake_x_publisher, fixed_clock
):
    result = await mcp.call_tool("post_now", version_id=await version_of("Out now."))

    assert result["isError"] is False, result
    posted = result["structuredContent"]
    assert posted["state"] == "published"
    assert posted["x_post_url"] == FIRST_X_POST
    assert posted["message"] == f"Published on X: {FIRST_X_POST}"
    assert posted["post_url"] == f"{POSTS_PAGE}/{posted['post_id']}"
    assert fake_x_publisher.published == [("access-1001-1", "Out now.")]


async def test_post_now_publishes_a_versions_final(
    connected, version, mcp, fake_x_publisher, fixed_clock
):
    result = await mcp.call_tool("post_now", version_id=version["id"])

    assert result["structuredContent"]["state"] == "published"
    assert result["structuredContent"]["source_version_id"] == version["id"]
    assert fake_x_publisher.published == [("access-1001-1", "The final, version one.")]


async def test_scheduling_a_thread_version_copies_every_part_in_order(
    connected, thread_version, mcp, fixed_clock
):
    result = await mcp.call_tool(
        "schedule_post", version_id=thread_version["id"], publish_at="2026-10-10T14:00:00Z"
    )

    assert result["isError"] is False, result
    scheduled = result["structuredContent"]
    assert [part["text"] for part in scheduled["parts"]] == THREAD_FINAL
    assert scheduled["source_version_id"] == thread_version["id"]


async def test_post_now_on_a_thread_version_publishes_the_whole_thread(
    connected, thread_version, mcp, fake_x_publisher, fixed_clock
):
    result = await mcp.call_tool("post_now", version_id=thread_version["id"])

    assert result["isError"] is False, result
    posted = result["structuredContent"]
    assert posted["state"] == "published"
    assert [part["live"] for part in posted["parts"]] == [True, True, True]
    assert posted["message"] == f"Published on X: {FIRST_X_POST}"
    assert [text for _, text in fake_x_publisher.published] == THREAD_FINAL
    assert fake_x_publisher.replied_to == [None, "1890000000000000001", "1890000000000000002"]


async def test_post_now_that_x_refuses_says_it_failed_and_why(
    connected, mcp, fake_x_publisher, fixed_clock, version_of
):
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Duplicate content.")

    result = await mcp.call_tool("post_now", version_id=await version_of("Duplicate."))

    assert result["isError"] is False, result
    posted = result["structuredContent"]
    assert posted["state"] == "failed"
    assert posted["failed_reason"] == "X refused the post: Duplicate content."
    assert posted["message"] == "Failed. X refused the post: Duplicate content."


async def test_post_now_into_a_community_publishes_it_there(
    connected, known_community, mcp, fake_x_publisher, fixed_clock, version_of
):
    result = await mcp.call_tool(
        "post_now",
        version_id=await version_of("Hello Community."),
        community=COMMUNITY_URL,
        share_with_followers=True,
    )

    assert result["structuredContent"]["state"] == "published"
    assert result["structuredContent"]["community"] == COMMUNITY
    assert fake_x_publisher.published_to == [(COMMUNITY_ID, True)]


async def test_a_community_post_x_refuses_fails_with_the_membership_hint(
    connected, known_community, mcp, fake_x_publisher, fixed_clock, version_of
):
    fake_x_publisher.fail_publish = XPostRejectedError(403, "You are not permitted.")

    result = await mcp.call_tool(
        "post_now", version_id=await version_of("Hello Community."), community=COMMUNITY_ID
    )

    assert result["structuredContent"]["state"] == "failed"
    assert result["structuredContent"]["message"] == (
        "Failed. X refused the post: You are not permitted. Check that your X account is a "
        "member of this Community and allowed to post in it."
    )


@pytest.mark.parametrize("error", [XRateLimitedError("429"), XNotReceivedError("ConnectError")])
async def test_post_now_x_didnt_take_says_pumpkit_keeps_trying(
    connected, mcp, fake_x_publisher, fixed_clock, error, version_of
):
    fake_x_publisher.fail_publish = error

    result = await mcp.call_tool("post_now", version_id=await version_of("Out now."))

    assert result["isError"] is False, result
    posted = result["structuredContent"]
    assert posted["state"] == "scheduled"
    assert posted["message"] == "X was busy. Pumpkit will keep trying for the next 15 minutes."


ALREADY_SCHEDULED = "This Post already has a Scheduled post. Edit it, or unschedule it first."


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("schedule_post", {"parts": ["Typed."], "publish_at": "2026-10-10T14:00:00Z"}),
        ("post_now", {"parts": ["Typed."]}),
    ],
)
async def test_typed_parts_instead_of_a_version_are_refused_and_nothing_is_stored(
    connected, mcp, fake_x_publisher, fixed_clock, name, arguments
):
    result = await mcp.call_tool(name, **arguments)

    assert result["isError"] is True, result
    assert (await scheduled_posts_through_mcp(mcp)) == []
    assert fake_x_publisher.published == []


async def _scheduled_in(state: str, mcp, version_id: str, fake_x_publisher) -> dict:
    """The Scheduled post of the Version's Post, left in `state`."""
    if state == "scheduled":
        result = await mcp.call_tool(
            "schedule_post", version_id=version_id, publish_at="2026-10-10T14:00:00Z"
        )
    else:
        if state == "failed":
            fake_x_publisher.fail_publish = XPostRejectedError(403, "Nope")
        result = await mcp.call_tool("post_now", version_id=version_id)
        fake_x_publisher.fail_publish = None
    scheduled = result["structuredContent"]
    assert scheduled["state"] == state, result
    return scheduled


@pytest.mark.parametrize("state", ["scheduled", "published", "failed"])
@pytest.mark.parametrize(
    ("name", "arguments"),
    [("schedule_post", {"publish_at": "2026-10-10T15:00:00Z"}), ("post_now", {})],
)
async def test_a_second_scheduled_post_for_the_same_post_is_refused(
    connected, mcp, version_of, fake_x_publisher, fixed_clock, state, name, arguments
):
    version_id = await version_of("Once.")
    first = await _scheduled_in(state, mcp, version_id, fake_x_publisher)
    published_before = list(fake_x_publisher.published)

    result = await mcp.call_tool(name, version_id=version_id, **arguments)

    assert error_text(result) == ALREADY_SCHEDULED
    listed = await scheduled_posts_through_mcp(mcp)
    assert [s["id"] for s in listed] == [first["id"]]
    assert fake_x_publisher.published == published_before


async def test_deleting_a_failed_scheduled_post_lets_its_post_be_scheduled_again(
    connected, mcp, version_of, fake_x_publisher, fixed_clock
):
    version_id = await version_of("Retry me.")
    failed = await _scheduled_in("failed", mcp, version_id, fake_x_publisher)

    deleted = await mcp.call_tool("delete_scheduled_post", scheduled_post_id=failed["id"])
    again = await mcp.call_tool(
        "schedule_post", version_id=version_id, publish_at="2026-10-10T14:00:00Z"
    )

    assert deleted["isError"] is False, deleted
    assert again["isError"] is False, again
    assert again["structuredContent"]["state"] == "scheduled"


async def _give_feedback(mcp, fake_llm, post_id: str) -> dict:
    fake_llm.replies = [written("sketch two"), {"post": "The final, version two."}]
    return await mcp.call_tool("give_feedback", post_id=post_id, feedback="punchier")


@pytest.mark.parametrize(
    ("state", "refusal"),
    [
        (
            "scheduled",
            "This Post is scheduled, so it takes no Feedback. "
            "Edit its text, or unschedule it first.",
        ),
        (
            "published",
            "This Post is published, so it takes no Feedback. Start a new Post to write another.",
        ),
    ],
)
async def test_feedback_on_a_scheduled_or_published_post_is_refused(
    connected, version, mcp, fake_llm, fake_x_publisher, fixed_clock, state, refusal
):
    await _scheduled_in(state, mcp, version["id"], fake_x_publisher)

    result = await _give_feedback(mcp, fake_llm, version["post_id"])

    assert error_text(result) == refusal
    assert fake_llm.replies, "no model was called"


@pytest.mark.parametrize("state", [None, "failed"])
async def test_feedback_on_a_draft_or_failed_post_writes_the_next_version(
    connected, version, mcp, fake_llm, fake_x_publisher, fixed_clock, state
):
    if state is not None:
        await _scheduled_in(state, mcp, version["id"], fake_x_publisher)

    result = await _give_feedback(mcp, fake_llm, version["post_id"])

    assert result["isError"] is False, result
    assert result["structuredContent"]["number"] == 2
    assert result["structuredContent"]["parts"][0]["text"] == "The final, version two."


async def test_feedback_on_an_unscheduled_post_writes_the_next_version(
    connected, version, mcp, fake_llm, fake_x_publisher, fixed_clock
):
    scheduled = await _scheduled_in("scheduled", mcp, version["id"], fake_x_publisher)
    await mcp.call_tool("delete_scheduled_post", scheduled_post_id=scheduled["id"])

    result = await _give_feedback(mcp, fake_llm, version["post_id"])

    assert result["isError"] is False, result
