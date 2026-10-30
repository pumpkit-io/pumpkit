"""
Listing Posts by status through `GET /posts` and the `list_posts` tool: which Posts each status
holds (ADR 0015), the order of each, the counts, paging, and what each item carries.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from pumpkit.auth.models import User
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.posts.formats import format_of
from pumpkit.posts.models import ATTEMPT_FAILED, ATTEMPT_SUCCEEDED, Post, VersionAttempt
from pumpkit.scheduling.models import (
    FAILED,
    PUBLISHED,
    PUBLISHING,
    SCHEDULED,
    ScheduledPost,
    ScheduledPostPart,
    ScheduledPostState,
)
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.mcp_client import error_text
from tests.posts.writing_replies import written, written_thread

POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
NO_POSTS = {"draft": 0, "scheduled": 0, "published": 0, "failed": 0}


@pytest.fixture
def seed_post(db, user):
    """
    Store a Post of `user` with a Version of each of `versions`' Parts, the last written at
    `written_at`, and with a Scheduled post in `state` when given. Returns the Post's id.
    """

    async def _seed(
        *versions: list[str],
        written_at: datetime = T0,
        state: Optional[ScheduledPostState] = None,
        publish_at: datetime = T0,
        published_at: Optional[datetime] = None,
        scheduled_parts: Optional[list[str]] = None,
        live: int = 0,
        community: Optional[tuple[str, str]] = None,
        failed_reason: Optional[str] = None,
        owner: Optional[User] = None,
    ) -> str:
        post = Post(
            user_id=(owner or user).id,
            brief=f"About {versions[0][0] if versions else 'nothing'}",
            corpus_post_ids=[],
            created_at=written_at - timedelta(hours=len(versions)),
        )
        db.add(post)
        attempts = []
        for number, parts in enumerate(versions, start=1):
            attempts.append(
                VersionAttempt(
                    post=post,
                    sequence=number,
                    format=format_of(parts),
                    status=ATTEMPT_SUCCEEDED,
                    version_number=number,
                    sketch_parts=parts,
                    parts=parts,
                    created_at=written_at - timedelta(hours=len(versions) - number),
                )
            )
        db.add_all(attempts)
        await db.flush()
        if state is not None:
            texts = scheduled_parts or versions[-1]
            db.add(
                ScheduledPost(
                    user_id=post.user_id,
                    x_user_id="x-user",
                    post_id=post.id,
                    parts=[
                        ScheduledPostPart(
                            position=i,
                            text=text,
                            x_post_id=f"18900000000000000{i:02d}" if i < live else None,
                        )
                        for i, text in enumerate(texts)
                    ],
                    community_id=community[0] if community else None,
                    community_name=community[1] if community else None,
                    share_with_followers=community is not None,
                    publish_at=publish_at,
                    published_at=published_at,
                    state=state,
                    failed_reason=failed_reason,
                    retry_count=0,
                    created_at=T0,
                    updated_at=T0,
                )
            )
        await db.commit()
        return post.id

    return _seed


async def _listed(client, status: Optional[str] = None, **paging) -> dict:
    params = {**({"status": status} if status else {}), **paging}
    response = await client.get(POSTS, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _ids(client, status: str) -> list[str]:
    return [item["id"] for item in (await _listed(client, status))["data"]]


async def test_a_user_without_posts_lists_none_with_every_count_at_zero(client):
    assert await _listed(client, "draft") == {"data": [], "counts": NO_POSTS, "next_offset": None}


async def test_each_status_lists_the_posts_its_scheduled_post_gives_it(client, seed_post):
    draft = await seed_post(["Draft."])
    scheduled = await seed_post(["Waits."], state=SCHEDULED)
    publishing = await seed_post(["Going out."], state=PUBLISHING)
    published = await seed_post(["Went out."], state=PUBLISHED, published_at=T0, live=1)
    failed = await seed_post(["Refused."], state=FAILED, failed_reason="X refused it.")

    assert await _ids(client, "draft") == [draft]
    assert set(await _ids(client, "scheduled")) == {scheduled, publishing}
    assert await _ids(client, "published") == [published]
    assert await _ids(client, "failed") == [failed]
    assert (await _listed(client, "draft"))["counts"] == {
        "draft": 1,
        "scheduled": 2,
        "published": 1,
        "failed": 1,
    }


async def test_a_thread_that_failed_partway_lists_as_failed(client, seed_post):
    failed = await seed_post(["One.", "Two."], state=FAILED, live=1, failed_reason="Part 2 failed.")

    assert await _ids(client, "failed") == [failed]
    assert await _ids(client, "scheduled") == []


async def test_a_post_with_no_version_is_left_out_of_every_list_and_count(
    client, db, user, seed_post
):
    no_version = Post(user_id=user.id, brief="Never written", corpus_post_ids=[], created_at=T0)
    db.add(no_version)
    await db.flush()
    db.add(
        VersionAttempt(
            post_id=no_version.id,
            sequence=1,
            format="post",
            status=ATTEMPT_FAILED,
            error="LLMError: down",
            created_at=T0,
        )
    )
    await db.commit()
    draft = await seed_post(["Written."])

    listed = await _listed(client, "draft")

    assert [item["id"] for item in listed["data"]] == [draft]
    assert listed["counts"]["draft"] == 1


async def test_another_users_posts_are_left_out(client, db, seed_post):
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.flush()
    await seed_post(["Bob's."], owner=bob)
    await seed_post(["Bob's scheduled."], owner=bob, state=SCHEDULED)

    assert await _listed(client, "draft") == {"data": [], "counts": NO_POSTS, "next_offset": None}


async def test_scheduled_lists_the_soonest_first(client, seed_post):
    later = await seed_post(["Later."], state=SCHEDULED, publish_at=T0 + timedelta(days=2))
    soonest = await seed_post(["Soonest."], state=SCHEDULED, publish_at=T0 + timedelta(hours=1))
    middle = await seed_post(["Middle."], state=PUBLISHING, publish_at=T0 + timedelta(days=1))

    assert await _ids(client, "scheduled") == [soonest, middle, later]


async def test_drafts_list_the_newest_version_first(client, seed_post):
    old = await seed_post(["Old."], written_at=T0)
    # Started first, but its second Version is the newest of all.
    revised = await seed_post(["First."], ["Revised."], written_at=T0 + timedelta(days=2))
    newer = await seed_post(["Newer."], written_at=T0 + timedelta(days=1))

    assert await _ids(client, "draft") == [revised, newer, old]


async def test_published_lists_the_most_recently_published_first(client, seed_post):
    first = await seed_post(["First."], state=PUBLISHED, published_at=T0, live=1)
    last = await seed_post(
        ["Last."], state=PUBLISHED, publish_at=T0, published_at=T0 + timedelta(days=2), live=1
    )
    middle = await seed_post(["Mid."], state=PUBLISHED, published_at=T0 + timedelta(days=1), live=1)

    assert await _ids(client, "published") == [last, middle, first]


async def test_failed_lists_the_most_recently_due_first(client, seed_post):
    earliest = await seed_post(["Earliest."], state=FAILED, publish_at=T0)
    latest = await seed_post(["Latest."], state=FAILED, publish_at=T0 + timedelta(days=2))
    middle = await seed_post(["Middle."], state=FAILED, publish_at=T0 + timedelta(days=1))

    assert await _ids(client, "failed") == [latest, middle, earliest]


async def test_without_a_status_every_post_lists_with_the_newest_version_first(client, seed_post):
    draft = await seed_post(["Draft."], written_at=T0)
    scheduled = await seed_post(["Waits."], written_at=T0 + timedelta(days=1), state=SCHEDULED)

    assert [item["id"] for item in (await _listed(client))["data"]] == [scheduled, draft]


async def test_show_more_pages_through_a_status_with_the_counts_on_every_page(client, seed_post):
    ids = [await seed_post([f"Draft {n}."], written_at=T0 - timedelta(days=n)) for n in range(5)]
    await seed_post(["Waits."], state=SCHEDULED)

    first = await _listed(client, "draft", limit=2)
    second = await _listed(client, "draft", limit=2, offset=first["next_offset"])
    last = await _listed(client, "draft", limit=2, offset=second["next_offset"])

    assert [item["id"] for item in first["data"]] == ids[:2]
    assert [item["id"] for item in second["data"]] == ids[2:4]
    assert [item["id"] for item in last["data"]] == ids[4:]
    assert (first["next_offset"], second["next_offset"], last["next_offset"]) == (2, 4, None)
    expected_counts = {**NO_POSTS, "draft": 5, "scheduled": 1}
    assert first["counts"] == second["counts"] == last["counts"] == expected_counts


@pytest.mark.parametrize(
    ("params", "detail"),
    [
        ({"status": "waiting"}, "Input should be 'draft', 'scheduled', 'published' or 'failed'"),
        ({"limit": 0}, "Input should be greater than or equal to 1"),
        ({"limit": 51}, "Input should be less than or equal to 50"),
        ({"offset": -1}, "Input should be greater than or equal to 0"),
    ],
)
async def test_a_status_or_page_outside_the_bounds_is_refused(client, params, detail):
    response = await client.get(POSTS, params=params)

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == detail


async def test_a_draft_carries_its_latest_versions_text_and_no_scheduled_post(client, seed_post):
    post_id = await seed_post(["First take."], ["Hook line.\nMore.", "Second part."], written_at=T0)

    [item] = (await _listed(client, "draft"))["data"]

    assert item == {
        "id": post_id,
        "brief": "About First take.",
        "status": "draft",
        "parts": ["Hook line.\nMore.", "Second part."],
        "format": "thread",
        "version_count": 2,
        "latest_version_at": "2026-10-01T09:00:00Z",
        "scheduled_post": None,
    }


async def test_a_scheduled_post_carries_its_own_text_and_a_summary_of_its_scheduled_post(
    client, seed_post
):
    post_id = await seed_post(
        ["The Version's text."],
        state=SCHEDULED,
        publish_at=T0 + timedelta(days=1),
        scheduled_parts=["Edited after scheduling."],
        community=("1500000000000000001", "Indie Hackers"),
    )

    [item] = (await _listed(client, "scheduled"))["data"]

    assert item["parts"] == ["Edited after scheduling."]
    assert (item["format"], item["version_count"]) == ("post", 1)
    assert item["scheduled_post"] == {
        "id": item["scheduled_post"]["id"],
        "state": "scheduled",
        "publish_at": "2026-10-02T09:00:00Z",
        "published_at": None,
        "community": {
            "id": "1500000000000000001",
            "name": "Indie Hackers",
            "url": "https://x.com/i/communities/1500000000000000001",
        },
        "share_with_followers": True,
        "failed_reason": None,
        "x_post_url": None,
    }
    assert item["id"] == post_id


async def test_a_published_post_carries_its_link_on_x(client, seed_post):
    await seed_post(["Went out."], state=PUBLISHED, published_at=T0 + timedelta(minutes=1), live=1)

    [item] = (await _listed(client, "published"))["data"]

    assert item["scheduled_post"]["published_at"] == "2026-10-01T09:01:00Z"
    assert item["scheduled_post"]["x_post_url"] == "https://x.com/i/web/status/1890000000000000000"


async def test_a_thread_that_failed_partway_carries_its_reason_and_its_first_parts_link(
    client, with_author_and_x, fake_llm, fake_x_publisher
):
    fake_llm.replies = [written_thread(["a", "b"]), {"parts": ["Live one.", "Refused two."]}]
    post = (await client.post(POSTS, json={"brief": "ship", "format": "thread"})).json()
    fake_x_publisher.fail_publish = XPostRejectedError(403, "Nope")
    fake_x_publisher.fail_publish_on = 2
    failed = await client.post(
        SCHEDULED_POSTS,
        json={"post_id": post["id"], "publish_now": True},
    )

    [item] = (await _listed(client, "failed"))["data"]

    assert item["parts"] == ["Live one.", "Refused two."]
    assert item["scheduled_post"]["failed_reason"] == failed.json()["failed_reason"]
    assert item["scheduled_post"]["x_post_url"] == failed.json()["parts"][0]["x_post_url"]


async def test_unscheduling_moves_the_post_back_to_drafts(client, with_author_and_x, fake_llm):
    fake_llm.replies = [written("sketch"), {"post": "Version one."}]
    post = (await client.post(POSTS, json={"brief": "ship"})).json()
    scheduled = (
        await client.post(
            SCHEDULED_POSTS,
            json={
                "post_id": post["id"],
                "publish_at": "2026-10-11T09:00:00Z",
            },
        )
    ).json()
    assert (await _listed(client, "scheduled"))["counts"]["scheduled"] == 1

    await client.delete(f"{SCHEDULED_POSTS}/{scheduled['id']}")

    listed = await _listed(client, "draft")
    assert [item["id"] for item in listed["data"]] == [post["id"]]
    assert listed["counts"] == {**NO_POSTS, "draft": 1}


async def test_a_user_who_is_not_subscribed_still_lists_their_posts(client, seed_post):
    draft = await seed_post(["Draft."])

    assert await _ids(client, "draft") == [draft]


@pytest.fixture
async def with_author_and_x(client, subscribed, fake_x_reader, connect_x, fixed_clock) -> None:
    await connect_x()
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(post_id="levelsio-0", text="levelsio post", posted_at=T0)
    ]
    added = await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    assert added.status_code == 201, added.text


async def test_the_list_posts_tool_lists_a_status_with_each_scheduled_post_and_the_counts(
    subscribed, mcp, client, seed_post
):
    await seed_post(["Draft."])
    failed = await seed_post(["Refused."], state=FAILED, failed_reason="X refused it.")

    result = await mcp.call_tool("list_posts", status="failed")

    assert result["isError"] is False
    assert result["structuredContent"] == await _listed(client, "failed")
    assert [item["id"] for item in result["structuredContent"]["data"]] == [failed]
    assert result["structuredContent"]["counts"] == {**NO_POSTS, "draft": 1, "failed": 1}


async def test_the_list_posts_tool_lists_every_post_without_a_status_and_pages(
    subscribed, mcp, seed_post
):
    newest = await seed_post(["Newest."], written_at=T0 + timedelta(days=1), state=SCHEDULED)
    older = await seed_post(["Older."], written_at=T0)

    first = (await mcp.call_tool("list_posts", limit=1))["structuredContent"]
    second = (await mcp.call_tool("list_posts", limit=1, offset=1))["structuredContent"]

    assert [item["id"] for item in first["data"]] == [newest]
    assert first["data"][0]["status"] == "scheduled"
    assert first["next_offset"] == 1
    assert [item["id"] for item in second["data"]] == [older]
    assert second["next_offset"] is None


@pytest.mark.parametrize(
    ("arguments", "detail"),
    [
        ({"limit": 0}, "Input should be greater than or equal to 1"),
        ({"limit": 51}, "Input should be less than or equal to 50"),
        ({"offset": -1}, "Input should be greater than or equal to 0"),
    ],
)
async def test_the_list_posts_tool_refuses_a_page_outside_the_bounds(
    subscribed, mcp, arguments, detail
):
    result = await mcp.call_tool("list_posts", **arguments)

    assert error_text(result) == detail


async def test_the_list_posts_tool_refuses_a_status_it_doesnt_know(subscribed, mcp):
    result = await mcp.call_tool("list_posts", status="waiting")

    assert "Input should be 'draft', 'scheduled', 'published' or 'failed'" in error_text(result)


async def test_list_scheduled_posts_is_no_longer_a_tool(subscribed, mcp):
    tools = await mcp.list_tools()

    assert "list_scheduled_posts" not in tools
    assert tools["list_posts"]["annotations"]["readOnlyHint"] is True


async def test_the_old_scheduled_posts_list_is_gone(client):
    assert (await client.get(SCHEDULED_POSTS)).status_code == 405


def test_the_status_column_compares_states_as_the_enum_on_postgres():
    # SQLite compares anything, so only the compiled SQL shows what Postgres would refuse.
    from sqlalchemy.dialects import postgresql

    from pumpkit.scheduling.service import _post_status_column

    sql = str((_post_status_column() == "scheduled").compile(dialect=postgresql.asyncpg.dialect()))
    assert sql.count("::scheduled_post_state_enum") == 4
    assert "WHEN $1::VARCHAR" not in sql
