"""
Spacing Reach warnings (ADR 0032): a time less than 2 hours from another of the User's Scheduled
posts, waiting or Published, and two Ideas of one Brief on the same day in the request's time zone.
"""

import pytest

from pumpkit.core.db.session import get_session_maker
from pumpkit.main import app
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import HUMANIZED_POST, POST_IDEAS, ideas, planned_post

BRIEFS = "/api/v1/briefs"
POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"


async def _schedule(client, post_id: str, **when) -> dict:
    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, **when})
    assert response.status_code == 201, response.text
    return response.json()


async def _warnings_at(client, post_id: str, publish_at=None, **headers) -> list[dict]:
    params = {"publish_at": publish_at} if publish_at else {}
    response = await client.get(f"{POSTS}/{post_id}/reach-warnings", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["reach_warnings"]


async def test_a_waiting_post_an_hour_away_warns(
    client, subscribed, connect_x, fixed_clock, post_with
):
    await connect_x()
    await _schedule(client, await post_with("Waiting."), publish_at="2026-10-10T15:00:00Z")
    post_id = await post_with("Ship small things.")

    assert await _warnings_at(client, post_id, "2026-10-10T16:00:00Z") == [
        {
            "code": "nearby_post",
            "part": None,
            "message": "Your other post goes out on Sat 10 Oct at 15:00 UTC, less than 2 hours "
            "away, so the two split each other's reach. Pick a time 2 hours from your other post.",
        }
    ]


def _codes(warnings: list[dict]) -> list[tuple[str, None]]:
    return [(w["code"], w["part"]) for w in warnings]


async def test_a_waiting_post_three_hours_away_does_not_warn(
    client, subscribed, connect_x, fixed_clock, post_with
):
    await connect_x()
    await _schedule(client, await post_with("Waiting."), publish_at="2026-10-10T15:00:00Z")
    post_id = await post_with("Ship small things.")

    assert await _warnings_at(client, post_id, "2026-10-10T18:00:00Z") == []


async def test_a_published_post_an_hour_before_warns(
    client, subscribed, connect_x, fixed_clock, post_with
):
    await connect_x()
    await _schedule(client, await post_with("Out already."), publish_now=True)
    post_id = await post_with("Ship small things.")

    [warning] = await _warnings_at(client, post_id, "2026-10-10T13:00:00Z")

    assert warning["code"] == "nearby_post"
    assert warning["message"].startswith("Your other post went out on Sat 10 Oct at 12:00 UTC")


async def test_post_now_counts_as_now(client, subscribed, connect_x, fixed_clock, post_with):
    await connect_x()
    await _schedule(client, await post_with("Waiting."), publish_at="2026-10-10T13:00:00Z")
    post_id = await post_with("Ship small things.")

    assert _codes(await _warnings_at(client, post_id)) == [("nearby_post", None)]
    posted = await _schedule(client, post_id, publish_now=True)
    assert _codes(posted["reach_warnings"]) == [("nearby_post", None)]


async def test_a_failed_post_does_not_count(
    client, subscribed, connect_x, fixed_clock, fake_x_publisher, post_with
):
    await connect_x()
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Nope")
    failed = await _schedule(client, await post_with("Failed."), publish_now=True)
    assert failed["state"] == "failed"
    post_id = await post_with("Ship small things.")

    assert await _warnings_at(client, post_id, "2026-10-10T13:00:00Z") == []


async def test_scheduling_and_editing_answer_with_the_spacing_warning(
    client, subscribed, connect_x, fixed_clock, post_with
):
    await connect_x()
    await _schedule(client, await post_with("Waiting."), publish_at="2026-10-10T15:00:00Z")
    post_id = await post_with("Ship small things.")

    scheduled = await _schedule(client, post_id, publish_at="2026-10-10T20:00:00Z")
    edited = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled['id']}", json={"publish_at": "2026-10-10T16:30:00Z"}
    )

    assert scheduled["reach_warnings"] == []
    assert edited.status_code == 200, edited.text
    assert _codes(edited.json()["reach_warnings"]) == [("nearby_post", None)]


async def test_a_scheduled_posts_own_time_warns_on_its_post(
    client, subscribed, connect_x, fixed_clock, post_with
):
    await connect_x()
    await _schedule(client, await post_with("Waiting."), publish_at="2026-10-10T15:00:00Z")
    post_id = await post_with("Ship small things. Tag a friend who ships.")
    await _schedule(client, post_id, publish_at="2026-10-10T14:00:00Z")

    read = await client.get(f"{POSTS}/{post_id}")

    assert _codes(read.json()["reach_warnings"]) == [("tag_ask", 1), ("nearby_post", None)]


async def test_the_scheduling_tools_give_the_spacing_warning(
    subscribed, connect_x, fixed_clock, mcp, post_with
):
    await connect_x()
    waiting = await mcp.call_tool(
        "schedule_post", post_id=await post_with("Waiting."), publish_at="2026-10-10T15:00:00Z"
    )
    post_id = await post_with("Ship small things.")
    scheduled = await mcp.call_tool(
        "schedule_post", post_id=post_id, publish_at="2026-10-10T16:00:00Z"
    )
    edited = await mcp.call_tool(
        "edit_scheduled_post",
        scheduled_post_id=scheduled["structuredContent"]["id"],
        publish_at="2026-10-10T15:30:00Z",
    )
    read = await mcp.call_tool("get_post", post_id=post_id)

    assert waiting["structuredContent"]["reach_warnings"] == []
    assert _codes(scheduled["structuredContent"]["reach_warnings"]) == [("nearby_post", None)]
    assert _codes(edited["structuredContent"]["reach_warnings"]) == [("nearby_post", None)]
    assert _codes(read["structuredContent"]["reach_warnings"]) == [("nearby_post", None)]


@pytest.fixture
async def split_posts(client, subscribed, connect_x, fixed_clock, writing_session_maker, fake_llm):
    """Plans a Brief and writes its two split Ideas: their Posts' ids, in the Brief's order."""
    await connect_x()
    await save_positioning(client)
    app.dependency_overrides[get_session_maker] = lambda: writing_session_maker
    fake_llm.standing[POST_IDEAS] = ideas(
        planned_post("Two lessons."), [planned_post("Pain first."), planned_post("Skip OAuth.")]
    )
    fake_llm.standing[HUMANIZED_POST] = {"post": "A lesson.", "first_reply": None}
    planned = await client.post(BRIEFS, json={"brief": "Two things I learned."})
    assert planned.status_code == 201, planned.text
    split = [idea["id"] for idea in planned.json()["ideas"] if not idea["whole_brief"]]
    written = await client.post(f"{BRIEFS}/{planned.json()['id']}/posts", json={"idea_ids": split})
    assert written.status_code == 202, written.text
    brief = await client.get(f"{BRIEFS}/{planned.json()['id']}")
    return [idea["post"]["id"] for idea in brief.json()["ideas"] if idea["post"]]


async def test_two_ideas_of_a_brief_on_one_day_warn(client, split_posts):
    first, second = split_posts
    await _schedule(client, first, publish_at="2026-10-11T09:00:00Z")

    assert await _warnings_at(client, second, "2026-10-11T20:00:00Z") == [
        {
            "code": "same_brief_same_day",
            "part": None,
            "message": "Another idea from this brief goes out the same day, Sun 11 Oct, so the "
            "two compete for the same readers.",
        }
    ]


async def test_the_same_day_is_the_one_in_the_requests_time_zone(client, split_posts):
    first, second = split_posts
    # 19:00 and 21:00 on 11 Oct in New York, across midnight in UTC.
    await _schedule(client, first, publish_at="2026-10-11T23:00:00Z")

    in_new_york = await _warnings_at(
        client, second, "2026-10-12T01:00:00Z", **{"X-Time-Zone": "America/New_York"}
    )
    in_utc = await _warnings_at(client, second, "2026-10-12T01:00:00Z")

    assert _codes(in_new_york) == [("same_brief_same_day", None)]
    assert in_utc == []


async def test_the_tools_go_by_the_time_zone_given(client, split_posts, mcp):
    first, second = split_posts
    await _schedule(client, first, publish_at="2026-10-11T23:00:00Z")

    in_new_york = await mcp.call_tool(
        "schedule_post",
        post_id=second,
        publish_at="2026-10-12T01:00:00Z",
        time_zone="America/New_York",
    )
    in_utc = await mcp.call_tool("get_post", post_id=second)
    read_in_new_york = await mcp.call_tool("get_post", post_id=second, time_zone="America/New_York")

    assert _codes(in_new_york["structuredContent"]["reach_warnings"]) == [
        ("same_brief_same_day", None)
    ]
    assert in_utc["structuredContent"]["reach_warnings"] == []
    assert _codes(read_in_new_york["structuredContent"]["reach_warnings"]) == [
        ("same_brief_same_day", None)
    ]
