"""
Discarding a Draft through `DELETE /posts/{id}` and the `delete_post` tool (ADR 0025): the Post,
its Versions, its Media with their files and its Upload links go for good, its Idea stays on the
Brief as not written, and the Generations it used stay used. Every other Post is refused.
"""

import asyncio
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy import update

from pumpkit.core.db.session import get_session_maker
from pumpkit.core.llm import LLMError
from pumpkit.main import app
from pumpkit.posts.writing_state import WRITING_TIMEOUT
from pumpkit.scheduling.models import FAILED, PUBLISHED, PUBLISHING, ScheduledPost
from tests.mcp_client import error_text
from tests.media_files import png
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import (
    HUMANIZED_POST,
    POST_IDEAS,
    REVISED_POST,
    SKETCHED_POST,
    ideas,
    planned_post,
    started_post_id,
)

BRIEFS = "/api/v1/briefs"
POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
USAGE = "/api/v1/usage"
LATER = "2026-10-10T14:00:00Z"
CORE_IDEAS = [
    "Make sure the pain is real before you build.",
    "Charge at least 20 euros a month.",
    "Don't make OAuth integrations your core value.",
]
WHOLE = "Three lessons from a failed SaaS."


@pytest.fixture
async def draft(client, subscribed, connect_x, fake_llm, fixed_clock) -> dict:
    """A Brief with one Idea, its Post a Draft: the Brief as planning it answered."""
    await connect_x()
    await save_positioning(client)
    fake_llm.replies = [{"post": "Version one."}]
    planned = await client.post(BRIEFS, json={"brief": "ship small things"})
    assert started_post_id(planned)
    return planned.json()


def _post_id(brief: dict) -> str:
    [post_id] = [idea["post"]["id"] for idea in brief["ideas"] if idea["post"]]
    return post_id


async def _discard(client, post_id: str):
    return await client.delete(f"{POSTS}/{post_id}")


async def _brief(client, brief_id: str) -> dict:
    response = await client.get(f"{BRIEFS}/{brief_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def _schedule(client, post_id: str) -> str:
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})
    assert scheduled.status_code == 201, scheduled.text
    return scheduled.json()["id"]


async def _generations_used(client) -> int:
    return (await client.get(USAGE)).json()["allowance"]["generations"]["used"]


async def test_a_discarded_draft_is_gone_and_its_idea_stays_not_written(client, draft):
    post_id = _post_id(draft)

    response = await _discard(client, post_id)

    assert response.status_code == 204, response.text
    assert (await client.get(f"{POSTS}/{post_id}")).status_code == 404
    [idea] = (await _brief(client, draft["id"]))["ideas"]
    assert idea["id"] == draft["ideas"][0]["id"]
    assert idea["post"] is None
    listed = (await client.get(POSTS)).json()
    assert listed["data"] == []
    assert listed["counts"]["draft"] == 0


async def test_a_discarded_draft_can_be_written_again_from_its_idea(client, draft, fake_llm):
    assert (await _discard(client, _post_id(draft))).status_code == 204
    fake_llm.replies = [{"post": "Written again."}]

    written = await client.post(
        f"{BRIEFS}/{draft['id']}/posts", json={"idea_ids": [draft["ideas"][0]["id"]]}
    )

    assert written.status_code == 202, written.text
    post = (await _brief(client, draft["id"]))["ideas"][0]["post"]
    assert post["text"]["parts"][0]["text"] == "Written again."


async def test_discarding_twice_finds_nothing_the_second_time(client, draft):
    post_id = _post_id(draft)
    assert (await _discard(client, post_id)).status_code == 204

    assert (await _discard(client, post_id)).status_code == 404


async def test_another_users_draft_is_not_found(client, draft, sign_in_as_another_subscribed_user):
    post_id = _post_id(draft)
    await sign_in_as_another_subscribed_user()

    assert (await _discard(client, post_id)).status_code == 404


async def test_the_generation_a_discarded_draft_used_stays_used(client, draft, fake_llm):
    post_id = _post_id(draft)
    fake_llm.replies = [{"post": "Version two."}]
    assert (await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "x"})).is_success
    assert await _generations_used(client) == 2

    assert (await _discard(client, post_id)).status_code == 204

    assert await _generations_used(client) == 2


async def test_a_scheduled_post_is_refused(client, draft):
    post_id = _post_id(draft)
    await _schedule(client, post_id)

    response = await _discard(client, post_id)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        "This post is scheduled, so it can't be discarded. Unschedule it first."
    )
    assert (await client.get(f"{POSTS}/{post_id}")).status_code == 200


@pytest.mark.parametrize(
    ("state", "detail"),
    [
        (PUBLISHING, "This post is scheduled, so it can't be discarded. Unschedule it first."),
        (PUBLISHED, "This post is published, so it can't be discarded."),
        (
            FAILED,
            "This post failed, so it can't be discarded. Post it again, or unschedule it first.",
        ),
    ],
)
async def test_a_post_publishing_published_or_failed_is_refused(client, db, draft, state, detail):
    post_id = _post_id(draft)
    scheduled_post_id = await _schedule(client, post_id)
    await db.execute(
        update(ScheduledPost).where(ScheduledPost.id == scheduled_post_id).values(state=state)
    )
    await db.commit()

    response = await _discard(client, post_id)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == detail
    assert (await client.get(f"{POSTS}/{post_id}")).status_code == 200


async def test_an_unscheduled_post_is_a_draft_again_and_can_be_discarded(client, draft):
    post_id = _post_id(draft)
    scheduled_post_id = await _schedule(client, post_id)
    assert (await client.delete(f"{SCHEDULED_POSTS}/{scheduled_post_id}")).status_code == 204

    assert (await _discard(client, post_id)).status_code == 204


async def test_a_post_being_written_is_refused(
    client, subscribed, fake_llm, fixed_clock, background_tasks
):
    await save_positioning(client)
    held = asyncio.Event()
    fake_llm.held[SKETCHED_POST] = held
    fake_llm.replies = [{"post": "Version one."}]
    planned = await client.post(BRIEFS, json={"brief": "ship small things"})
    post_id = _post_id(planned.json())

    response = await _discard(client, post_id)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        "This post is still being written, so it can't be discarded yet."
    )
    held.set()
    await background_tasks.wait()
    assert (await client.get(f"{POSTS}/{post_id}")).json()["status"] == "draft"


async def test_a_post_whose_first_version_was_never_written_is_refused(
    client, subscribed, fake_llm, fixed_clock, fake_posthog
):
    await save_positioning(client)
    fake_llm.standing[HUMANIZED_POST] = LLMError("provider down")
    planned = await client.post(BRIEFS, json={"brief": "ship small things"})
    post_id = _post_id(planned.json())
    assert (await client.get(f"{POSTS}/{post_id}")).json()["writing_state"] == "not_written"

    response = await _discard(client, post_id)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        "This post has no version yet, so it can't be discarded. Retry writing it instead."
    )


async def test_a_draft_whose_feedback_is_being_written_is_refused(
    client, draft, fake_llm, background_tasks
):
    post_id = _post_id(draft)
    revising = asyncio.Event()
    fake_llm.held[REVISED_POST] = revising
    fake_llm.replies = [{"post": "Version two."}]
    assert (await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "x"})).is_success

    response = await _discard(client, post_id)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == (
        "This post is still being written, so it can't be discarded yet."
    )
    revising.set()
    await background_tasks.wait()


async def test_a_write_that_outlived_the_timeout_records_nothing_once_its_draft_is_discarded(
    client, subscribed, fake_llm, clock, background_tasks, writing_session_maker
):
    app.dependency_overrides[get_session_maker] = lambda: writing_session_maker
    await save_positioning(client)
    fake_llm.replies = [{"post": "Version one."}]
    planned = await client.post(BRIEFS, json={"brief": "ship small things"})
    await background_tasks.wait()
    brief = planned.json()
    post_id = _post_id(brief)
    revising = asyncio.Event()
    fake_llm.held[REVISED_POST] = revising
    fake_llm.replies = [{"post": "Version two."}]
    assert (await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "x"})).is_success
    clock.advance(WRITING_TIMEOUT + timedelta(seconds=1))

    assert (await _discard(client, post_id)).status_code == 204
    revising.set()
    await background_tasks.wait()

    assert (await client.get(f"{POSTS}/{post_id}")).status_code == 404
    assert (await _brief(client, brief["id"]))["ideas"][0]["post"] is None


async def test_its_media_and_their_files_are_deleted(client, draft, file_storage):
    post_id = _post_id(draft)
    attached = await client.post(
        f"{POSTS}/{post_id}/text/parts/1/media", files={"file": ("a.png", png(40, 30), "image/png")}
    )
    assert attached.status_code == 201, attached.text
    media_id = attached.json()["id"]
    assert await file_storage.list_files("media")

    assert (await _discard(client, post_id)).status_code == 204

    assert await file_storage.list_files("media") == []
    assert (await client.get(f"/api/v1/media/{media_id}/preview")).status_code == 404


async def test_its_upload_links_stop_working(client, draft, mcp, new_browser):
    post_id = _post_id(draft)
    link = (await mcp.call_tool("attach_media", post_id=post_id))["structuredContent"]

    assert (await _discard(client, post_id)).status_code == 204

    path = urlsplit(link["upload_url"]).path
    upload = await new_browser().post(path, files={"file": ("a.png", png(40, 30), "image/png")})
    assert upload.status_code == 404, upload.text


async def test_the_other_posts_of_its_brief_close_up(client, subscribed, fake_llm, fixed_clock):
    await save_positioning(client)
    fake_llm.standing[POST_IDEAS] = ideas(
        planned_post(WHOLE), [planned_post(core_idea) for core_idea in CORE_IDEAS]
    )
    fake_llm.standing[HUMANIZED_POST] = {"post": "A post.", "first_reply": None}
    planned = (await client.post(BRIEFS, json={"brief": "Three lessons."})).json()
    split = [idea for idea in planned["ideas"] if not idea["whole_brief"]]
    written = await client.post(
        f"{BRIEFS}/{planned['id']}/posts", json={"idea_ids": [idea["id"] for idea in split]}
    )
    assert written.status_code == 202, written.text
    first, second, third = [idea["post"]["id"] for idea in written.json()["ideas"] if idea["post"]]

    assert (await _discard(client, second)).status_code == 204

    after = (await client.get(f"{POSTS}/{third}")).json()["place_in_brief"]
    assert after == {
        "position": 2,
        "post_count": 2,
        "previous_post_id": first,
        "next_post_id": None,
    }
    ideas_after = (await _brief(client, planned["id"]))["ideas"]
    assert [idea["post"] is not None for idea in ideas_after] == [False, True, False, True]


async def test_the_delete_post_tool_discards_a_draft(client, draft, mcp):
    post_id = _post_id(draft)

    result = await mcp.call_tool("delete_post", post_id=post_id)

    assert result["isError"] is False, result
    assert result["structuredContent"] == {
        "message": "The post and its versions are deleted.",
        "brief_id": draft["id"],
        "brief_url": f"http://localhost:5173/briefs/{draft['id']}",
    }
    assert (await client.get(f"{POSTS}/{post_id}")).status_code == 404


async def test_the_delete_post_tool_refuses_a_scheduled_post(client, draft, mcp):
    post_id = _post_id(draft)
    await _schedule(client, post_id)

    result = await mcp.call_tool("delete_post", post_id=post_id)

    assert result["isError"] is True
    assert error_text(result) == (
        "This post is scheduled, so it can't be discarded. Unschedule it first."
    )


async def test_the_delete_post_tool_is_destructive(subscribed, mcp):
    tools = await mcp.list_tools()

    assert tools["delete_post"]["annotations"]["destructiveHint"] is True


async def test_the_instructions_say_only_a_draft_is_discarded_and_to_ask_first(subscribed, mcp):
    instructions = (await mcp.initialize())["instructions"]

    assert "`delete_post` discards a draft for good" in instructions
    assert "get the user's yes first" in instructions
