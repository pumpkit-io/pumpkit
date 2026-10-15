"""The Scheduled post MCP tools, refusing what the web routes refuse, in the same words."""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, update

from pumpkit.auth.models import User
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.billing.models import Subscription
from pumpkit.core.config import settings
from pumpkit.posts.models import ATTEMPT_SUCCEEDED, Post, VersionAttempt
from pumpkit.scheduling.models import SCHEDULED, ScheduledPost
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.mcp_client import error_text

SCHEDULED_PAGE = "http://localhost:5173/scheduled"


async def _connect_x(client: AsyncClient) -> None:
    started = await client.post("/api/v1/x-connection/authorizations")
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
    completed = await client.post(
        "/api/v1/x-connection/authorizations/complete", json={"code": "c", "state": state}
    )
    assert completed.status_code == 200, completed.text


@pytest.fixture
async def connected(client, subscribed, fake_x_publisher) -> None:
    await _connect_x(client)


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
    fake_llm.replies = [{"post": "draft one"}, {"post": "The final, version one."}]
    started = await client.post("/api/v1/posts", json={"brief": "ship small things"})
    assert started.status_code == 201, started.text
    return started.json()["versions"][0]


async def test_scheduling_typed_text_lists_it_with_the_scheduled_page_link(
    connected, mcp, fixed_clock
):
    result = await mcp.call_tool(
        "schedule_post", text="  Shipping on Monday.  ", publish_at="2026-10-10T16:00:00+02:00"
    )

    assert result["isError"] is False, result
    scheduled = result["structuredContent"]
    assert scheduled["text"] == "Shipping on Monday."
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


async def test_scheduling_a_version_copies_its_final_and_records_the_version(
    connected, version, mcp, fixed_clock
):
    result = await mcp.call_tool(
        "schedule_post", version_id=version["id"], publish_at="2026-10-10T14:00:00Z"
    )

    assert result["isError"] is False, result
    assert result["structuredContent"]["text"] == "The final, version one."
    assert result["structuredContent"]["source_version_id"] == version["id"]


async def test_scheduling_another_users_version_is_refused_as_not_found(
    connected, mcp, db, fixed_clock
):
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.flush()
    bobs_post = Post(user_id=bob.id, brief="bob's", corpus_post_ids=[], created_at=fixed_clock())
    db.add(bobs_post)
    await db.flush()
    bobs_version = VersionAttempt(
        post_id=bobs_post.id,
        sequence=1,
        status=ATTEMPT_SUCCEEDED,
        version_number=1,
        final="Bob's words.",
        created_at=fixed_clock(),
    )
    db.add(bobs_version)
    await db.commit()

    result = await mcp.call_tool(
        "schedule_post", version_id=bobs_version.id, publish_at="2026-10-10T14:00:00Z"
    )

    assert error_text(result) == "Version not found."
    assert (await mcp.call_tool("list_scheduled_posts"))["structuredContent"]["data"] == []


@pytest.mark.parametrize("arguments", [{}, {"text": "Mine.", "version_id": "version_attempt_1"}])
async def test_scheduling_needs_either_text_or_a_version(connected, mcp, fixed_clock, arguments):
    result = await mcp.call_tool("schedule_post", publish_at="2026-10-10T14:00:00Z", **arguments)

    assert error_text(result) == "Give either the text or a Version id, not both."


async def _schedule(mcp, text: str = "Shipping on Monday.", at: str = "2026-10-10T14:00:00Z"):
    return await mcp.call_tool("schedule_post", text=text, publish_at=at)


async def test_scheduling_without_an_x_connection_links_to_the_scheduled_page(
    subscribed, mcp, fixed_clock
):
    result = await _schedule(mcp)

    assert error_text(result) == f"Connect your X account first. {SCHEDULED_PAGE}"


async def test_scheduling_on_an_x_connection_that_needs_reconnecting_links_to_the_scheduled_page(
    connected, mcp, db, fixed_clock
):
    await db.execute(update(XConnection).values(needs_reconnect=True))
    await db.commit()

    result = await _schedule(mcp)

    assert error_text(result) == (
        f"X no longer accepts Pumpkit's access to your account. Reconnect X first. {SCHEDULED_PAGE}"
    )


async def test_a_post_over_the_x_accounts_limit_is_refused(connected, mcp, fixed_clock):
    result = await _schedule(mcp, text="x" * 281)

    assert error_text(result) == "This post is 281 characters by X's count, over the 280 limit."


@pytest.mark.parametrize(
    ("at", "message"),
    [
        ("2026-10-10T12:00:00Z", "Pick a time at least a minute from now."),
        ("2026-10-10T14:00:30Z", "Pick a time on a whole minute."),
    ],
)
async def test_a_time_the_web_app_refuses_is_refused(connected, mcp, fixed_clock, at, message):
    result = await _schedule(mcp, at=at)

    assert error_text(result) == message


async def test_a_time_without_its_utc_offset_is_refused(connected, mcp, fixed_clock):
    result = await _schedule(mcp, at="2026-10-10T14:00:00")

    assert error_text(result) == "Input should have timezone info"


async def test_the_monthly_cap_counts_scheduled_posts_from_the_web_app_too(
    connected, client, mcp, fixed_clock, monkeypatch
):
    monkeypatch.setattr(settings, "SCHEDULED_POSTS_MONTHLY_CAP", 2)
    from_web = await client.post(
        "/api/v1/scheduled-posts", json={"text": "First", "publish_at": "2026-10-11T09:00:00Z"}
    )
    assert from_web.status_code == 201, from_web.text
    await _schedule(mcp, text="Second", at="2026-10-30T09:00:00Z")

    result = await _schedule(mcp, text="Third", at="2026-10-12T09:00:00Z")

    assert error_text(result) == (
        "You have 2 Scheduled posts in October 2026, the most for one month. "
        "The cap resets on November 1, 2026."
    )


COMMUNITY_ID = "1493446837214187523"
COMMUNITY_URL = f"https://x.com/i/communities/{COMMUNITY_ID}"
NOT_A_COMMUNITY = (
    "That isn't a Community. Paste its URL from X, like https://x.com/i/communities/123, or its ID."
)


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
        text="Shipping on Monday.",
        publish_at="2026-10-10T14:00:00Z",
        community=f"{COMMUNITY_URL}?s=20",
        share_with_followers=share_with_followers,
    )

    assert result["isError"] is False, result
    assert result["structuredContent"]["community"] == COMMUNITY
    assert result["structuredContent"]["share_with_followers"] is share_with_followers


@pytest.mark.parametrize(
    ("pasted", "message"),
    [
        ("https://x.com/levelsio", NOT_A_COMMUNITY),
        ("123", "X has no Community with that ID. Check the URL."),
    ],
)
async def test_a_community_x_doesnt_know_is_refused(connected, mcp, fixed_clock, pasted, message):
    result = await mcp.call_tool(
        "schedule_post", text="Hi.", publish_at="2026-10-10T14:00:00Z", community=pasted
    )

    assert error_text(result) == message
    assert (await mcp.call_tool("list_scheduled_posts"))["structuredContent"]["data"] == []


async def _post_now_on_the_web(client: AsyncClient, text: str = "Out now.") -> dict:
    response = await client.post(
        "/api/v1/scheduled-posts", json={"text": text, "publish_now": True}
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
        text="  Launch day.  ",
        publish_at="2026-10-11T11:30:00+02:00",
    )

    assert result["isError"] is False, result
    assert result["structuredContent"] == {
        **scheduled,
        "text": "Launch day.",
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


async def test_editing_nothing_is_refused(connected, mcp, fixed_clock):
    scheduled = (await _schedule(mcp))["structuredContent"]

    result = await mcp.call_tool("edit_scheduled_post", scheduled_post_id=scheduled["id"])

    assert error_text(result) == (
        "Change the text, the publish time, the Community or sharing with followers."
    )


async def test_editing_into_a_community_x_doesnt_know_is_refused(connected, mcp, fixed_clock):
    scheduled = (await _schedule(mcp))["structuredContent"]

    result = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=scheduled["id"], community="not a community"
    )

    assert error_text(result) == NOT_A_COMMUNITY


PUBLISHING_STARTED = "Publishing has started, so this Scheduled post can no longer change."


async def test_a_published_scheduled_post_can_be_neither_edited_nor_deleted(
    connected, client, mcp, fixed_clock
):
    published = await _post_now_on_the_web(client)

    edited = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=published["id"], text="Changed"
    )
    deleted = await mcp.call_tool("delete_scheduled_post", scheduled_post_id=published["id"])

    assert error_text(edited) == error_text(deleted) == PUBLISHING_STARTED


async def test_another_users_scheduled_post_is_not_found(connected, mcp, db, fixed_clock):
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.flush()
    bobs = ScheduledPost(
        user_id=bob.id,
        x_user_id="2002",
        text="Bob's.",
        publish_at=fixed_clock() + timedelta(hours=2),
        state=SCHEDULED,
        created_at=fixed_clock(),
        updated_at=fixed_clock(),
    )
    db.add(bobs)
    await db.commit()

    edited = await mcp.call_tool("edit_scheduled_post", scheduled_post_id=bobs.id, text="Mine?")
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
        "schedule_post", text="Hi.", publish_at="2026-10-10T14:00:00Z", community=COMMUNITY_ID
    )

    result = await mcp.call_tool("list_past_communities")

    assert result["structuredContent"] == {"data": [COMMUNITY]}


async def test_tools_list_shows_deleting_a_scheduled_post_as_destructive(subscribed, mcp):
    tools = await mcp.list_tools()

    assert tools["delete_scheduled_post"]["annotations"]["destructiveHint"] is True
    for name in ("schedule_post", "edit_scheduled_post"):
        assert tools[name]["annotations"] == {"readOnlyHint": False, "destructiveHint": False}
    for name in ("list_scheduled_posts", "list_past_communities", "connect_x"):
        assert tools[name]["annotations"]["readOnlyHint"] is True


async def test_connect_x_links_to_the_scheduled_page(subscribed, mcp):
    result = await mcp.call_tool("connect_x")

    assert result["isError"] is False, result
    assert result["structuredContent"]["url"] == SCHEDULED_PAGE
    assert SCHEDULED_PAGE in result["structuredContent"]["message"]


@pytest.mark.parametrize("name", ["schedule_post", "edit_scheduled_post", "delete_scheduled_post"])
async def test_the_write_tools_allow_10_calls_a_minute(connected, mcp, fixed_clock, name):
    arguments = {
        "schedule_post": {"text": "Hi.", "publish_at": "2026-10-10T14:00:00Z"},
        "edit_scheduled_post": {"scheduled_post_id": "scheduled_post_missing", "text": "Hi."},
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
        ("schedule_post", {"text": "Hi.", "publish_at": "2026-10-10T14:00:00Z"}),
        ("list_scheduled_posts", {}),
        ("edit_scheduled_post", {"scheduled_post_id": "scheduled_post_missing", "text": "Hi."}),
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
    sells_no_plans, client, fake_x_publisher, mcp, fixed_clock
):
    await _connect_x(client)

    result = await _schedule(mcp)

    assert result["isError"] is False, result


FIRST_X_POST = "https://x.com/i/web/status/1890000000000000001"


async def test_post_now_publishes_typed_text_and_links_to_it_on_x(
    connected, mcp, fake_x_publisher, fixed_clock
):
    result = await mcp.call_tool("post_now", text="Out now.")

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

    result = await mcp.call_tool("post_now", text="Duplicate.")

    assert result["isError"] is False, result
    posted = result["structuredContent"]
    assert posted["state"] == "failed"
    assert posted["failed_reason"] == "X refused the post: Duplicate content."
    assert posted["message"] == "Failed. X refused the post: Duplicate content."
