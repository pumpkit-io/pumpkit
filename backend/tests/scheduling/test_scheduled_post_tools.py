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
from pumpkit.scheduling.models import SCHEDULED, ScheduledPost, ScheduledPostPart
from pumpkit.x_connection.x_publisher import (
    XNotReceivedError,
    XPostRejectedError,
    XRateLimitedError,
)
from tests.mcp_client import error_text
from tests.posts.writing_replies import written

SCHEDULED_PAGE = "http://localhost:5173/scheduled"


@pytest.fixture
async def connected(subscribed, fixed_clock, connect_x) -> None:
    await connect_x()


@pytest.fixture
async def version(client, subscribed, fake_x_reader, fake_llm) -> dict:
    """The first Version of a new Post, whose Final is "The final, version one."."""
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    added = await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    assert added.status_code == 201, added.text
    fake_llm.replies = [written("draft one"), {"post": "The final, version one."}]
    started = await client.post("/api/v1/posts", json={"brief": "ship small things"})
    assert started.status_code == 201, started.text
    return started.json()["versions"][0]


async def test_scheduling_typed_text_lists_it_with_the_scheduled_page_link(
    connected, mcp, fixed_clock
):
    result = await mcp.call_tool(
        "schedule_post", parts=["  Shipping on Monday.  "], publish_at="2026-10-10T16:00:00+02:00"
    )

    assert result["isError"] is False, result
    scheduled = result["structuredContent"]
    assert scheduled["parts"][0]["text"] == "Shipping on Monday."
    assert scheduled["state"] == "scheduled"
    assert scheduled["publish_at"] == "2026-10-10T14:00:00Z"
    assert scheduled["source_version_id"] is None
    assert scheduled["community"] is None
    assert scheduled["scheduled_page_url"] == SCHEDULED_PAGE
    listed = await mcp.call_tool("list_scheduled_posts")
    assert listed["structuredContent"] == {
        "data": [{key: value for key, value in scheduled.items() if key != "scheduled_page_url"}],
        "scheduled_page_url": SCHEDULED_PAGE,
    }


async def test_scheduling_parts_answers_with_each_part_in_order_and_none_live(
    connected, mcp, fixed_clock
):
    result = await mcp.call_tool(
        "schedule_post",
        parts=["The first Part.", "The second Part."],
        publish_at="2026-10-10T14:00:00Z",
    )

    assert result["isError"] is False, result
    assert result["structuredContent"]["parts"] == [
        {"text": "The first Part.", "live": False, "x_post_url": None},
        {"text": "The second Part.", "live": False, "x_post_url": None},
    ]


async def test_post_now_with_parts_publishes_them_as_a_thread(
    connected, mcp, fake_x_publisher, fixed_clock
):
    result = await mcp.call_tool("post_now", parts=["Thread start.", "Thread end."])

    assert result["isError"] is False, result
    published = result["structuredContent"]
    assert published["state"] == "published"
    assert published["x_post_url"] == "https://x.com/i/web/status/1890000000000000001"
    assert [part["live"] for part in published["parts"]] == [True, True]
    assert fake_x_publisher.replied_to == [None, "1890000000000000001"]


async def test_editing_replaces_the_parts_and_refuses_one_over_the_limit_by_name(
    connected, mcp, fixed_clock
):
    scheduled = (await _schedule(mcp))["structuredContent"]

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


async def _schedule(mcp, text: str = "Shipping on Monday.", at: str = "2026-10-10T14:00:00Z"):
    return await mcp.call_tool("schedule_post", parts=[text], publish_at=at)


async def test_scheduling_without_an_x_connection_links_to_the_scheduled_page(
    subscribed, mcp, fixed_clock
):
    result = await _schedule(mcp)

    assert error_text(result) == f"Connect your X account first. {SCHEDULED_PAGE}"


async def test_a_post_over_the_x_accounts_limit_is_refused(connected, mcp, fixed_clock):
    result = await _schedule(mcp, text="x" * 281)

    assert error_text(result) == "This post is 281 characters by X's count, over the 280 limit."


async def test_a_time_without_its_utc_offset_is_refused(connected, mcp, fixed_clock):
    result = await _schedule(mcp, at="2026-10-10T14:00:00")

    assert error_text(result) == "Input should have timezone info"


async def test_the_monthly_cap_counts_scheduled_posts_from_the_web_app_too(
    connected, client, mcp, fixed_clock, monkeypatch
):
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 2)
    from_web = await client.post(
        "/api/v1/scheduled-posts", json={"parts": ["First"], "publish_at": "2026-10-11T09:00:00Z"}
    )
    assert from_web.status_code == 201, from_web.text
    await _schedule(mcp, text="Second", at="2026-10-30T09:00:00Z")

    result = await _schedule(mcp, text="Third", at="2026-10-12T09:00:00Z")

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
    connected, known_community, mcp, fixed_clock, share_with_followers
):
    result = await mcp.call_tool(
        "schedule_post",
        parts=["Shipping on Monday."],
        publish_at="2026-10-10T14:00:00Z",
        community=f"{COMMUNITY_URL}?s=20",
        share_with_followers=share_with_followers,
    )

    assert result["isError"] is False, result
    assert result["structuredContent"]["community"] == COMMUNITY
    assert result["structuredContent"]["share_with_followers"] is share_with_followers


async def test_a_community_x_doesnt_know_is_refused(connected, mcp, fixed_clock):
    result = await mcp.call_tool(
        "schedule_post", parts=["Hi."], publish_at="2026-10-10T14:00:00Z", community="123"
    )

    assert error_text(result) == "X has no Community with that ID. Check the URL."
    assert (await mcp.call_tool("list_scheduled_posts"))["structuredContent"]["data"] == []


async def _post_now_on_the_web(client: AsyncClient, text: str = "Out now.") -> dict:
    response = await client.post(
        "/api/v1/scheduled-posts", json={"parts": [text], "publish_now": True}
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def failed(connected, client, fake_x_publisher, fixed_clock) -> dict:
    """A Scheduled post X refused when the User Posted it now in the web app."""
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Duplicate content.")
    failed = await _post_now_on_the_web(client, "Duplicate.")
    fake_x_publisher.fail_publish = None
    assert failed["state"] == "failed"
    return failed


async def test_the_list_says_why_a_scheduled_post_failed(failed, mcp, fixed_clock):
    listed = await mcp.call_tool("list_scheduled_posts", state="failed")

    [scheduled] = listed["structuredContent"]["data"]
    assert scheduled["state"] == "failed"
    assert scheduled["failed_reason"] == "X refused the post: Duplicate content."


async def test_editing_the_text_and_time_of_a_waiting_scheduled_post_saves_both(
    connected, mcp, fixed_clock
):
    scheduled = (await _schedule(mcp, text="Lanch day."))["structuredContent"]

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
    connected, known_community, mcp, fixed_clock
):
    scheduled = (await _schedule(mcp))["structuredContent"]

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
    connected, mcp, fixed_clock
):
    scheduled = (await _schedule(mcp))["structuredContent"]

    result = await mcp.call_tool(
        "edit_scheduled_post",
        scheduled_post_id=scheduled["id"],
        community=COMMUNITY_ID,
        to_profile=True,
    )

    assert error_text(result) == "Give either a Community or the profile, not both."


PUBLISHING_STARTED = "Publishing has started, so this Scheduled post can no longer change."


async def test_a_published_scheduled_post_can_be_neither_edited_nor_deleted(
    connected, client, mcp, fixed_clock
):
    published = await _post_now_on_the_web(client)

    edited = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=published["id"], parts=["Changed"]
    )
    deleted = await mcp.call_tool("delete_scheduled_post", scheduled_post_id=published["id"])

    assert error_text(edited) == error_text(deleted) == PUBLISHING_STARTED


async def test_a_scheduled_post_being_published_can_be_neither_edited_nor_deleted(
    connected, mcp, db_session_maker, fixed_clock
):
    scheduled = (await _schedule(mcp, at="2026-10-10T12:02:00Z"))["structuredContent"]
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
    listed = await mcp.call_tool("list_scheduled_posts")
    assert [
        (post["parts"][0]["text"], post["state"]) for post in listed["structuredContent"]["data"]
    ] == [("Shipping on Monday.", "publishing")]


async def test_another_users_scheduled_post_is_not_found(connected, mcp, db, fixed_clock):
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.flush()
    bobs = ScheduledPost(
        user_id=bob.id,
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


async def test_deleting_a_waiting_scheduled_post_takes_it_off_the_list(connected, mcp, fixed_clock):
    scheduled = (await _schedule(mcp))["structuredContent"]

    result = await mcp.call_tool("delete_scheduled_post", scheduled_post_id=scheduled["id"])

    assert result["structuredContent"] == {
        "message": "The Scheduled post is deleted.",
        "scheduled_page_url": SCHEDULED_PAGE,
    }
    assert (await mcp.call_tool("list_scheduled_posts"))["structuredContent"]["data"] == []


async def test_deleting_a_failed_scheduled_post_takes_it_off_the_list(failed, mcp, fixed_clock):
    result = await mcp.call_tool("delete_scheduled_post", scheduled_post_id=failed["id"])

    assert result["isError"] is False, result
    assert (await mcp.call_tool("list_scheduled_posts"))["structuredContent"]["data"] == []


async def test_past_communities_are_the_ones_the_user_posted_to_before(
    connected, known_community, mcp, fixed_clock
):
    assert (await mcp.call_tool("list_past_communities"))["structuredContent"] == {"data": []}
    await mcp.call_tool(
        "schedule_post", parts=["Hi."], publish_at="2026-10-10T14:00:00Z", community=COMMUNITY_ID
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
    for name in ("list_scheduled_posts", "list_past_communities", "connect_x"):
        assert tools[name]["annotations"]["readOnlyHint"] is True


async def test_connect_x_links_to_the_scheduled_page(subscribed, mcp):
    result = await mcp.call_tool("connect_x")

    assert result["isError"] is False, result
    assert result["structuredContent"]["url"] == SCHEDULED_PAGE
    assert SCHEDULED_PAGE in result["structuredContent"]["message"]


@pytest.mark.parametrize(
    "name", ["schedule_post", "post_now", "edit_scheduled_post", "delete_scheduled_post"]
)
async def test_the_write_tools_allow_10_calls_a_minute(connected, mcp, fixed_clock, name):
    arguments = {
        "schedule_post": {"parts": ["Hi."], "publish_at": "2026-10-10T14:00:00Z"},
        "post_now": {"parts": ["x" * 281]},
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


@pytest.mark.parametrize("name", ["list_scheduled_posts", "list_past_communities", "connect_x"])
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
        ("schedule_post", {"parts": ["Hi."], "publish_at": "2026-10-10T14:00:00Z"}),
        ("post_now", {"parts": ["Hi."]}),
        ("list_scheduled_posts", {}),
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

    assert result["structuredContent"]["url"] == SCHEDULED_PAGE


async def test_every_user_schedules_on_an_instance_that_sells_no_plans(
    sells_no_plans, client, fake_x_publisher, mcp, fixed_clock, connect_x
):
    await connect_x()

    result = await _schedule(mcp)

    assert result["isError"] is False, result


FIRST_X_POST = "https://x.com/i/web/status/1890000000000000001"


async def test_post_now_publishes_typed_text_and_links_to_it_on_x(
    connected, mcp, fake_x_publisher, fixed_clock
):
    result = await mcp.call_tool("post_now", parts=["Out now."])

    assert result["isError"] is False, result
    posted = result["structuredContent"]
    assert posted["state"] == "published"
    assert posted["x_post_url"] == FIRST_X_POST
    assert posted["message"] == f"Published on X: {FIRST_X_POST}"
    assert posted["scheduled_page_url"] == SCHEDULED_PAGE
    assert fake_x_publisher.published == [("access-1001-1", "Out now.")]


async def test_post_now_publishes_a_versions_final(
    connected, version, mcp, fake_x_publisher, fixed_clock
):
    result = await mcp.call_tool("post_now", version_id=version["id"])

    assert result["structuredContent"]["state"] == "published"
    assert result["structuredContent"]["source_version_id"] == version["id"]
    assert fake_x_publisher.published == [("access-1001-1", "The final, version one.")]


async def test_post_now_that_x_refuses_says_it_failed_and_why(
    connected, mcp, fake_x_publisher, fixed_clock
):
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Duplicate content.")

    result = await mcp.call_tool("post_now", parts=["Duplicate."])

    assert result["isError"] is False, result
    posted = result["structuredContent"]
    assert posted["state"] == "failed"
    assert posted["failed_reason"] == "X refused the post: Duplicate content."
    assert posted["message"] == "Failed. X refused the post: Duplicate content."


async def test_post_now_into_a_community_publishes_it_there(
    connected, known_community, mcp, fake_x_publisher, fixed_clock
):
    result = await mcp.call_tool(
        "post_now", parts=["Hello Community."], community=COMMUNITY_URL, share_with_followers=True
    )

    assert result["structuredContent"]["state"] == "published"
    assert result["structuredContent"]["community"] == COMMUNITY
    assert fake_x_publisher.published_to == [(COMMUNITY_ID, True)]


async def test_a_community_post_x_refuses_fails_with_the_membership_hint(
    connected, known_community, mcp, fake_x_publisher, fixed_clock
):
    fake_x_publisher.fail_publish = XPostRejectedError(403, "You are not permitted.")

    result = await mcp.call_tool("post_now", parts=["Hello Community."], community=COMMUNITY_ID)

    assert result["structuredContent"]["state"] == "failed"
    assert result["structuredContent"]["message"] == (
        "Failed. X refused the post: You are not permitted. Check that your X account is a "
        "member of this Community and allowed to post in it."
    )


@pytest.mark.parametrize("error", [XRateLimitedError("429"), XNotReceivedError("ConnectError")])
async def test_post_now_x_didnt_take_says_pumpkit_keeps_trying(
    connected, mcp, fake_x_publisher, fixed_clock, error
):
    fake_x_publisher.fail_publish = error

    result = await mcp.call_tool("post_now", parts=["Out now."])

    assert result["isError"] is False, result
    posted = result["structuredContent"]
    assert posted["state"] == "scheduled"
    assert posted["message"] == "X was busy. Pumpkit will keep trying for the next 15 minutes."
