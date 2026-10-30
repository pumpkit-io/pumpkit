"""
Editing a Post's Text in place (ADR 0016), through `PUT /posts/{id}/text`. Only a Draft or a
Failed Post's Text changes, its number of Parts stays, and Parts live on X stay as they are.
"""

import pytest
from httpx import AsyncClient

from pumpkit.auth.models import User
from pumpkit.posts.models import Post
from pumpkit.x_connection.x_length import X_POST_MAX_CHARS
from pumpkit.x_connection.x_publisher import XPostRejectedError

POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
LATER = "2026-10-10T14:00:00Z"


def _part(text: str) -> dict:
    return {"text": text, "char_count": len(text), "char_limit": X_POST_MAX_CHARS}


async def _save(client: AsyncClient, post_id: str, *parts: str):
    return await client.put(f"{POSTS}/{post_id}/text", json={"parts": list(parts)})


async def _text_of(client: AsyncClient, post_id: str) -> dict:
    return (await client.get(f"{POSTS}/{post_id}")).json()["text"]


async def _schedule(client: AsyncClient, post_id: str, **when) -> dict:
    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, **when})
    assert response.status_code == 201, response.text
    return response.json()


async def test_saving_a_draft_stores_the_parts_as_the_edited_text(client, subscribed, post_with):
    post_id = await post_with("As written.")

    response = await _save(client, post_id, "As edited.")

    assert response.status_code == 200, response.text
    saved = {"format": "post", "parts": [_part("As edited.")], "version_number": 1, "edited": True}
    assert response.json() == saved
    assert await _text_of(client, post_id) == saved


async def test_saving_the_same_text_twice_is_harmless(client, subscribed, post_with):
    post_id = await post_with("One.", "Two.")

    first = await _save(client, post_id, "One, edited.", "Two.")
    second = await _save(client, post_id, "One, edited.", "Two.")

    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    assert await _text_of(client, post_id) == first.json()


async def test_saving_the_version_text_back_reads_as_not_edited(client, subscribed, post_with):
    post_id = await post_with("As written.")
    await _save(client, post_id, "As edited.")

    response = await _save(client, post_id, "As written.")

    assert response.status_code == 200, response.text
    assert response.json()["edited"] is False


async def test_a_thread_saves_each_part_and_stays_a_thread(client, subscribed, post_with):
    post_id = await post_with("One.", "Two.", "Three.")

    response = await _save(client, post_id, "One.", "Two, edited.", "Three.")

    assert response.status_code == 200, response.text
    assert response.json()["format"] == "thread"
    assert [p["text"] for p in response.json()["parts"]] == ["One.", "Two, edited.", "Three."]


async def test_the_text_keeps_the_parts_as_typed(client, subscribed, post_with):
    post_id = await post_with("One.", "Two.")

    response = await _save(client, post_id, "  One. ", "")

    assert response.status_code == 200, response.text
    assert [p["text"] for p in response.json()["parts"]] == ["  One. ", ""]


async def test_a_change_in_the_number_of_parts_is_refused(client, subscribed, post_with):
    post_id = await post_with("One.", "Two.")

    response = await _save(client, post_id, "One.", "Two.", "Three.")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Editing keeps the Text's 2 Parts. Give Feedback to change its shape."
    )
    assert [p["text"] for p in (await _text_of(client, post_id))["parts"]] == ["One.", "Two."]


async def test_a_failed_post_saves_the_parts_after_the_live_ones(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Live one.", "Refused two.")
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = 2
    assert (await _schedule(client, post_id, publish_now=True))["state"] == "failed"

    response = await _save(client, post_id, "Live one.", "Fixed two.")

    assert response.status_code == 200, response.text
    assert [p["text"] for p in response.json()["parts"]] == ["Live one.", "Fixed two."]


async def test_a_change_to_a_part_live_on_x_is_refused(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Live one.", "Refused two.")
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = 2
    assert (await _schedule(client, post_id, publish_now=True))["state"] == "failed"

    response = await _save(client, post_id, "Live one, edited.", "Fixed two.")

    assert response.status_code == 409
    assert response.json()["detail"] == "Part 1 is already on X, so it can't change."
    assert (await _text_of(client, post_id))["edited"] is False


async def test_saving_a_scheduled_post_is_refused(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("As written.")
    await _schedule(client, post_id, publish_at=LATER)

    response = await _save(client, post_id, "As edited.")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This Post is scheduled, so its Text is set. Edit its Scheduled post, or unschedule it"
        " first."
    )
    assert (await _text_of(client, post_id))["edited"] is False


async def test_saving_a_published_post_is_refused(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("As written.")
    await _schedule(client, post_id, publish_now=True)

    response = await _save(client, post_id, "As edited.")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This Post is published, so its Text is set. Start a new Post to write another."
    )


@pytest.fixture
async def bobs_post_id(db, fixed_clock) -> str:
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.flush()
    post = Post(user_id=bob.id, brief="bob's", corpus_post_ids=[], created_at=fixed_clock())
    db.add(post)
    await db.commit()
    return post.id


async def test_another_users_post_is_not_found(client, subscribed, bobs_post_id):
    response = await _save(client, bobs_post_id, "Mine now.")

    assert response.status_code == 404


async def test_a_user_who_is_not_subscribed_cannot_save(client, post_with):
    post_id = await post_with("As written.")

    response = await _save(client, post_id, "As edited.")

    assert response.status_code == 403
    assert (await _text_of(client, post_id))["edited"] is False


async def test_get_post_reports_the_text_as_edited_since_its_version(
    client, subscribed, post_with, mcp
):
    post_id = await post_with("As written.")
    await _save(client, post_id, "As edited.")

    read = (await mcp.call_tool("get_post", post_id=post_id))["structuredContent"]

    assert read["text"]["edited"] is True
    assert read["text"]["version_number"] == 1
    assert [p["text"] for p in read["text"]["parts"]] == ["As edited."]
    assert [p["text"] for p in read["versions"][0]["parts"]] == ["As written."]


async def test_scheduling_copies_the_edited_text(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("As written.")
    await _save(client, post_id, "As edited.")

    scheduled = await _schedule(client, post_id, publish_at=LATER)

    assert [p["text"] for p in scheduled["parts"]] == ["As edited."]


async def test_scheduling_a_text_with_a_blank_part_is_refused(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One.", "Two.")
    await _save(client, post_id, "One.", "  ")

    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})

    assert response.status_code == 422
    assert response.json()["detail"] == "Write Part 2 first."
    assert (await client.get(f"{POSTS}/{post_id}")).json()["status"] == "draft"


async def test_scheduling_copies_the_text_without_the_spaces_around_each_part(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("As written.")
    await _save(client, post_id, "  As edited.\n")

    scheduled = await _schedule(client, post_id, publish_at=LATER)

    assert [p["text"] for p in scheduled["parts"]] == ["As edited."]
