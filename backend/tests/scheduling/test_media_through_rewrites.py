"""
Feedback, a Format change and restoring a Version replace only the Text's words: each Part keeps
its Media, and Media of Parts the new Text no longer has goes last on its last Part.
"""

from datetime import datetime, timezone
from typing import Optional

import pytest
from httpx import Response
from sqlalchemy import update

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.main import app
from pumpkit.posts.llm import FakeLLM, get_llm
from pumpkit.posts.models import Media
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.media_files import png
from tests.posts.writing_replies import written, written_thread

POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
LATER = "2026-10-10T14:00:00Z"


@pytest.fixture
async def with_author(client, subscribed, fake_x_reader, connect_x):
    await connect_x()
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    added = await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    assert added.status_code == 201, added.text


async def _start_thread(client, fake_llm, *parts: str) -> str:
    fake_llm.replies = [written_thread(list(parts)), {"parts": list(parts)}]
    started = await client.post(POSTS, json={"brief": "ship small things", "format": "thread"})
    assert started.status_code == 201, started.text
    return started.json()["id"]


async def _attach(client, post_id: str, *, part: int, name: str = "photo.png") -> str:
    response = await client.post(
        f"{POSTS}/{post_id}/text/parts/{part}/media",
        files={"file": (name, png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _feedback(client, post_id: str, feedback: str, format: Optional[str] = None):
    body = {"feedback": feedback} if format is None else {"feedback": feedback, "format": format}
    response = await client.post(f"{POSTS}/{post_id}/versions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _media_by_part(client, post_id: str) -> list[list[str]]:
    text = (await client.get(f"{POSTS}/{post_id}")).json()["text"]
    return [[m["id"] for m in part["media"]] for part in text["parts"]]


async def test_feedback_keeps_each_parts_media_where_it_is(client, with_author, fake_llm):
    post_id = await _start_thread(client, fake_llm, "one", "two")
    first = await _attach(client, post_id, part=1)
    second = await _attach(client, post_id, part=2)
    fake_llm.replies = [written_thread(["uno", "dos"]), {"parts": ["uno", "dos"]}]

    await _feedback(client, post_id, "in Spanish")

    assert await _media_by_part(client, post_id) == [[first], [second]]


async def test_feedback_that_drops_parts_moves_their_media_last_on_the_last_part_in_order(
    client, with_author, fake_llm
):
    post_id = await _start_thread(client, fake_llm, "one", "two", "three", "four")
    on_two = await _attach(client, post_id, part=2)
    on_three = [await _attach(client, post_id, part=3) for _ in range(2)]
    on_four = await _attach(client, post_id, part=4)
    fake_llm.replies = [written_thread(["short", "shorter"]), {"parts": ["short", "shorter"]}]

    await _feedback(client, post_id, "two parts")

    assert await _media_by_part(client, post_id) == [[], [on_two, *on_three, on_four]]


async def test_switching_a_thread_to_a_single_post_puts_every_parts_media_on_it_in_order(
    client, with_author, fake_llm
):
    post_id = await _start_thread(client, fake_llm, "one", "two")
    on_one = await _attach(client, post_id, part=1)
    on_two = await _attach(client, post_id, part=2)
    fake_llm.replies = [written("one post"), {"post": "one post"}]

    await _feedback(client, post_id, "condense it", "post")

    assert await _media_by_part(client, post_id) == [[on_one, on_two]]


async def test_media_moved_onto_a_part_past_xs_rule_stays_and_scheduling_refuses_it(
    client, with_author, fake_llm
):
    post_id = await _start_thread(client, fake_llm, "one", "two")
    on_one = [await _attach(client, post_id, part=1) for _ in range(3)]
    on_two = [await _attach(client, post_id, part=2) for _ in range(2)]
    fake_llm.replies = [written("one post"), {"post": "one post"}]

    await _feedback(client, post_id, "condense it", "post")

    assert await _media_by_part(client, post_id) == [on_one + on_two]
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})
    assert scheduled.status_code == 422, scheduled.text
    assert scheduled.json()["code"] == "MEDIA_OVER_X_RULE"


async def test_restoring_a_version_keeps_each_parts_media(client, with_author, fake_llm):
    post_id = await _start_thread(client, fake_llm, "one", "two")
    fake_llm.replies = [written_thread(["uno", "dos"]), {"parts": ["uno", "dos"]}]
    await _feedback(client, post_id, "in Spanish")
    first = await _attach(client, post_id, part=1)
    second = await _attach(client, post_id, part=2)

    restored = await client.post(f"{POSTS}/{post_id}/versions/1/restore")

    assert restored.status_code == 200, restored.text
    assert [[m["id"] for m in p["media"]] for p in restored.json()["parts"]] == [[first], [second]]
    assert await _media_by_part(client, post_id) == [[first], [second]]


async def test_restoring_a_shorter_version_moves_media_onto_its_last_part_and_back_keeps_it(
    client, with_author, fake_llm
):
    post_id = await _start_thread(client, fake_llm, "one", "two")
    fake_llm.replies = [
        written_thread(["a", "b", "c"]),
        {"parts": ["a", "b", "c"]},
    ]
    await _feedback(client, post_id, "three parts")
    on_two = await _attach(client, post_id, part=2)
    on_three = await _attach(client, post_id, part=3)

    restored = await client.post(f"{POSTS}/{post_id}/versions/1/restore")

    assert restored.status_code == 200, restored.text
    assert await _media_by_part(client, post_id) == [[], [on_two, on_three]]
    assert (await client.post(f"{POSTS}/{post_id}/versions/2/restore")).status_code == 200
    assert await _media_by_part(client, post_id) == [[], [on_two, on_three], []]


async def test_media_attached_while_feedback_writes_stays_and_moves_with_its_part(
    client, with_author, fake_llm
):
    post_id = await _start_thread(client, fake_llm, "one", "two", "three")
    attached: list[str] = []

    class MeanwhileLLM(FakeLLM):
        async def structured(self, **kwargs):
            if not attached:
                attached.append(await _attach(client, post_id, part=3))
            return await super().structured(**kwargs)

    app.dependency_overrides[get_llm] = lambda: MeanwhileLLM(
        replies=[written_thread(["a", "b"]), {"parts": ["a", "b"]}]
    )

    await _feedback(client, post_id, "two parts")

    assert await _media_by_part(client, post_id) == [[], attached]


async def test_media_removed_while_feedback_writes_stays_removed(client, with_author, fake_llm):
    post_id = await _start_thread(client, fake_llm, "one", "two", "three")
    kept = await _attach(client, post_id, part=2)
    removed = await _attach(client, post_id, part=3)
    answers: list[Response] = []

    class MeanwhileLLM(FakeLLM):
        async def structured(self, **kwargs):
            if not answers:
                answers.append(await client.delete(f"{POSTS}/{post_id}/text/media/{removed}"))
            return await super().structured(**kwargs)

    app.dependency_overrides[get_llm] = lambda: MeanwhileLLM(
        replies=[written_thread(["a", "b"]), {"parts": ["a", "b"]}]
    )

    await _feedback(client, post_id, "two parts")

    assert answers[0].status_code == 204
    assert await _media_by_part(client, post_id) == [[], [kept]]


async def test_no_prompt_holds_anything_of_the_texts_media(client, db, with_author, fake_llm):
    post_id = await _start_thread(client, fake_llm, "one", "two")
    media_id = await _attach(client, post_id, part=1, name="beach-at-dawn.png")
    # No endpoint sets alt text yet, so it is written straight to the Media.
    await db.execute(
        update(Media).where(Media.id == media_id).values(alt_text="gulls over the harbour")
    )
    await db.commit()
    fake_llm.calls.clear()
    fake_llm.replies = [written("one post"), {"post": "one post"}]

    await _feedback(client, post_id, "condense it", "post")

    prompts = repr([call.messages for call in fake_llm.calls])
    for trace in (
        "beach-at-dawn",
        "gulls over the harbour",
        media_id,
        "/media/",
        "image/png",
        "PNG",
        "IHDR",
    ):
        assert trace not in prompts


async def _fail_after(client, fake_x_publisher, post_id: str, *, live: int) -> None:
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = live + 1
    posted = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert posted.json()["state"] == "failed", posted.text


async def test_restoring_a_version_that_would_put_media_on_a_part_already_on_x_is_refused(
    client, with_author, fake_llm, fake_x_publisher
):
    fake_llm.replies = [written("one post"), {"post": "one post"}]
    started = await client.post(POSTS, json={"brief": "ship small things"})
    post_id = started.json()["id"]
    fake_llm.replies = [written_thread(["a", "b", "c"]), {"parts": ["a", "b", "c"]}]
    await _feedback(client, post_id, "three parts", "thread")
    on_three = await _attach(client, post_id, part=3)
    await _fail_after(client, fake_x_publisher, post_id, live=2)

    restored = await client.post(f"{POSTS}/{post_id}/versions/1/restore")

    assert restored.status_code == 409, restored.text
    assert "Part 1 is already on X" in restored.json()["detail"]
    assert await _media_by_part(client, post_id) == [[], [], [on_three]]


async def test_feedback_that_would_put_media_on_a_part_already_on_x_is_refused(
    client, with_author, fake_llm, fake_x_publisher
):
    post_id = await _start_thread(client, fake_llm, "a", "b", "c")
    on_three = await _attach(client, post_id, part=3)
    await _fail_after(client, fake_x_publisher, post_id, live=2)
    fake_llm.replies = [written_thread(["a", "b"]), {"parts": ["a", "b"]}]

    refused = await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "two parts"})

    assert refused.status_code == 409, refused.text
    assert "Part 2 is already on X" in refused.json()["detail"]
    assert await _media_by_part(client, post_id) == [[], [], [on_three]]
    fake_llm.replies = [written_thread(["a", "b", "d"]), {"parts": ["a", "b", "d"]}]
    assert (await _feedback(client, post_id, "change the last part"))["number"] == 2
