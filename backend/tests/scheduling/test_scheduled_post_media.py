"""
Changing the Media on a waiting Scheduled post's own copy, through
`POST /scheduled-posts/{id}/parts/{n}/media` and `DELETE /scheduled-posts/{id}/media/{media_id}`,
and recopying the Text's with `copy_text` (ADR 0021). The Post's Text keeps its own Media.
"""

from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import update

from pumpkit.scheduling.models import PUBLISHING, ScheduledPost
from pumpkit.scheduling.publisher import run_pass
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.media_files import gif, png

POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
LATER = "2026-10-10T14:00:00Z"


async def _attach_to_text(client: AsyncClient, post_id: str, *, part: int = 1) -> dict:
    response = await client.post(
        f"{POSTS}/{post_id}/text/parts/{part}/media",
        files={"file": ("photo.png", png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _attach(client: AsyncClient, scheduled_post_id: str, data: bytes, *, part: int = 1):
    return await client.post(
        f"{SCHEDULED_POSTS}/{scheduled_post_id}/parts/{part}/media",
        files={"file": ("photo.png", data, "image/png")},
    )


async def _remove(client: AsyncClient, scheduled_post_id: str, media_id: str):
    return await client.delete(f"{SCHEDULED_POSTS}/{scheduled_post_id}/media/{media_id}")


async def _schedule(client: AsyncClient, post_id: str, **body) -> dict:
    response = await client.post(
        SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER, **body}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _read(client: AsyncClient, post_id: str) -> dict:
    response = await client.get(f"{POSTS}/{post_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _ids(parts: list[dict]) -> list[list[str]]:
    return [[m["id"] for m in part["media"]] for part in parts]


async def _with_part_one_live(client, fake_x_publisher, post_id: str) -> dict:
    """A Scheduled post whose Part 1 went out on X before Part 2 failed, then rescheduled."""
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = 2
    failed = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert failed.json()["state"] == "failed", failed.text
    fake_x_publisher.fail_publish = None
    rescheduled = await client.patch(
        f"{SCHEDULED_POSTS}/{failed.json()['id']}", json={"publish_at": LATER}
    )
    assert rescheduled.json()["state"] == "scheduled", rescheduled.text
    return rescheduled.json()


async def test_an_image_attached_to_a_scheduled_post_shows_on_its_part_and_not_on_the_text(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One", "Two")
    on_text = await _attach_to_text(client, post_id)
    scheduled_post = await _schedule(client, post_id)

    response = await _attach(client, scheduled_post["id"], png(30, 20), part=2)

    assert response.status_code == 201, response.text
    attached = response.json()
    assert attached["kind"] == "image"
    assert (attached["width"], attached["height"]) == (30, 20)
    read = await _read(client, post_id)
    assert read["scheduled_post"]["parts"][1]["media"] == [attached]
    assert _ids(read["scheduled_post"]["parts"]) == [[on_text["id"]], [attached["id"]]]
    assert _ids(read["text"]["parts"]) == [[on_text["id"]], []]
    preview = await client.get(f"/api/v1{attached['preview_url']}")
    assert preview.status_code == 200


async def test_a_scheduled_post_publishes_the_media_attached_to_it(
    client,
    subscribed,
    db_session_maker,
    file_storage,
    fake_x_publisher,
    fixed_clock,
    connect_x,
    post_with,
):
    await connect_x()
    post_id = await post_with("Goes out with a picture.")
    response = await client.post(
        SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": "2026-10-10T12:05:00Z"}
    )
    image = png(12, 34)
    attached = await _attach(client, response.json()["id"], image)
    assert attached.status_code == 201, attached.text
    fixed_clock.advance(timedelta(minutes=5))

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert [upload.data for upload in fake_x_publisher.uploads] == [image]
    assert fake_x_publisher.published_media == [[fake_x_publisher.uploads[0].media_id]]


async def test_a_fifth_image_on_a_scheduled_posts_part_is_refused_naming_the_part(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One", "Two")
    scheduled_post = await _schedule(client, post_id)
    for _ in range(4):
        assert (await _attach(client, scheduled_post["id"], png(), part=2)).status_code == 201

    response = await _attach(client, scheduled_post["id"], png(), part=2)

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "MEDIA_PART_FULL"
    assert response.json()["detail"] == (
        "Part 2 holds 4 images already. X takes up to 4 images, or 1 GIF, or 1 video, per post."
    )


async def test_a_file_that_isnt_an_image_pumpkit_takes_is_refused(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One")
    scheduled_post = await _schedule(client, post_id)

    response = await _attach(client, scheduled_post["id"], gif())

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "MEDIA_TYPE_UNSUPPORTED"
    assert _ids((await _read(client, post_id))["scheduled_post"]["parts"]) == [[]]


async def test_a_part_the_scheduled_post_does_not_have_is_not_found(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One")
    scheduled_post = await _schedule(client, post_id)

    response = await _attach(client, scheduled_post["id"], png(), part=2)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "This scheduled post has no part 2."


async def test_removing_media_from_a_scheduled_post_leaves_the_texts(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One")
    first = await _attach_to_text(client, post_id)
    second = await _attach_to_text(client, post_id)
    scheduled_post = await _schedule(client, post_id)

    response = await _remove(client, scheduled_post["id"], first["id"])

    assert response.status_code == 204, response.text
    read = await _read(client, post_id)
    assert _ids(read["scheduled_post"]["parts"]) == [[second["id"]]]
    assert _ids(read["text"]["parts"]) == [[first["id"], second["id"]]]


async def test_a_removed_image_makes_room_for_another(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One")
    scheduled_post = await _schedule(client, post_id)
    attached = [(await _attach(client, scheduled_post["id"], png())).json() for _ in range(4)]

    await _remove(client, scheduled_post["id"], attached[1]["id"])
    response = await _attach(client, scheduled_post["id"], png())

    assert response.status_code == 201, response.text
    read = await _read(client, post_id)
    assert _ids(read["scheduled_post"]["parts"]) == [
        [attached[0]["id"], attached[2]["id"], attached[3]["id"], response.json()["id"]]
    ]


async def test_removing_media_the_scheduled_post_does_not_hold_is_not_found(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One")
    only_on_text = await _attach_to_text(client, post_id)
    scheduled_post = await _schedule(client, post_id)
    await _remove(client, scheduled_post["id"], only_on_text["id"])

    response = await _remove(client, scheduled_post["id"], only_on_text["id"])

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "This scheduled post has no such media."


async def test_another_users_scheduled_post_is_not_found(
    client, subscribed, fixed_clock, connect_x, post_with, sign_in_as_another_subscribed_user
):
    await connect_x()
    post_id = await post_with("Mine")
    on_text = await _attach_to_text(client, post_id)
    scheduled_post = await _schedule(client, post_id)
    await sign_in_as_another_subscribed_user()

    attach = await _attach(client, scheduled_post["id"], png())
    remove = await _remove(client, scheduled_post["id"], on_text["id"])

    assert attach.status_code == 404, attach.text
    assert remove.status_code == 404, remove.text


async def test_a_part_already_on_x_keeps_its_media(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Live one.", "Waiting two.")
    live = await _attach_to_text(client, post_id)
    scheduled_post = await _with_part_one_live(client, fake_x_publisher, post_id)

    attach = await _attach(client, scheduled_post["id"], png(), part=1)
    remove = await _remove(client, scheduled_post["id"], live["id"])
    on_waiting_part = await _attach(client, scheduled_post["id"], png(), part=2)

    assert attach.status_code == 409, attach.text
    assert attach.json()["detail"] == "Part 1 is already on X, so its media is set."
    assert remove.status_code == 409, remove.text
    assert on_waiting_part.status_code == 201, on_waiting_part.text
    read = await _read(client, post_id)
    assert _ids(read["scheduled_post"]["parts"]) == [[live["id"]], [on_waiting_part.json()["id"]]]


async def test_a_published_scheduled_post_takes_no_media_changes(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Out already.")
    published = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert published.json()["state"] == "published", published.text
    on_text = await _attach_to_text(client, await post_with("Another"))

    attach = await _attach(client, published.json()["id"], png())
    remove = await _remove(client, published.json()["id"], on_text["id"])

    assert attach.status_code == 409, attach.text
    assert attach.json()["detail"] == (
        "Publishing has started, so this scheduled post can no longer change."
    )
    assert remove.status_code == 409, remove.text


async def test_a_scheduled_post_being_published_takes_no_media_changes(
    client, db, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Going out now.")
    on_text = await _attach_to_text(client, post_id)
    scheduled_post = await _schedule(client, post_id)
    await db.execute(
        update(ScheduledPost)
        .where(ScheduledPost.id == scheduled_post["id"])
        .values(state=PUBLISHING)
    )
    await db.commit()

    attach = await _attach(client, scheduled_post["id"], png())
    remove = await _remove(client, scheduled_post["id"], on_text["id"])

    assert attach.status_code == 409, attach.text
    assert remove.status_code == 409, remove.text
    read = await _read(client, post_id)
    assert _ids(read["scheduled_post"]["parts"]) == [[on_text["id"]]]


async def test_an_x_connection_without_media_write_is_asked_to_reconnect(
    client, db, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Old connection.")
    scheduled_post = await _schedule(client, post_id)
    await db.execute(
        update(XConnection).values(scopes="tweet.read tweet.write users.read offline.access")
    )
    await db.commit()

    response = await _attach(client, scheduled_post["id"], png())

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "X_RECONNECT_FOR_MEDIA"


async def test_copying_the_text_again_copies_its_media_too(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One", "Two")
    on_text = await _attach_to_text(client, post_id, part=2)
    scheduled_post = await _schedule(client, post_id)
    await _remove(client, scheduled_post["id"], on_text["id"])
    on_copy = (await _attach(client, scheduled_post["id"], png())).json()

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled_post['id']}", json={"copy_text": True}
    )

    assert response.status_code == 200, response.text
    assert _ids(response.json()["parts"]) == [[], [on_text["id"]]]
    assert on_copy["id"] not in str(await _read(client, post_id))


async def test_copying_the_text_again_keeps_the_media_of_parts_already_on_x(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Live one.", "Refused two.")
    live = await _attach_to_text(client, post_id)
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = 2
    failed = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert failed.json()["state"] == "failed", failed.text
    on_two = await _attach_to_text(client, post_id, part=2)

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{failed.json()['id']}", json={"copy_text": True}
    )

    assert response.status_code == 200, response.text
    assert _ids(response.json()["parts"]) == [[live["id"]], [on_two["id"]]]
