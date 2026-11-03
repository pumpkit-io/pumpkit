"""
Attaching Media to a Post's Text and removing it, through
`POST /posts/{id}/text/parts/{n}/media` and `DELETE /posts/{id}/text/media/{media_id}`, and
reading it back on `GET /posts/{id}` (ADR 0021). Only a Draft or a Failed Post's Text takes it.
"""

import struct
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import event, update

from pumpkit.posts import media_files
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.media_files import MB, gif, jpeg, padded, png, webp

POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
LATER = "2026-10-10T14:00:00Z"
BOUNDARY = b"b0undary"


async def _attach(
    client: AsyncClient,
    post_id: str,
    data: bytes,
    *,
    part: int = 1,
    name: str = "photo.png",
    content_type: str = "image/png",
):
    return await client.post(
        f"{POSTS}/{post_id}/text/parts/{part}/media",
        files={"file": (name, data, content_type)},
    )


async def _stream(client: AsyncClient, post_id: str, body: AsyncIterator[bytes], *, part: int = 1):
    """Uploads `body`, a multipart form sent as it is made, with no Content-Length."""
    return await client.post(
        f"{POSTS}/{post_id}/text/parts/{part}/media",
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY.decode()}"},
    )


def _file_head(data: bytes) -> list[bytes]:
    return [
        b"--" + BOUNDARY + b"\r\n",
        b'Content-Disposition: form-data; name="file"; filename="photo.png"\r\n',
        b"Content-Type: image/png\r\n\r\n",
        data,
    ]


FILE_END = b"\r\n--" + BOUNDARY + b"--\r\n"


async def _media_of(client: AsyncClient, post_id: str) -> list[list[dict]]:
    response = await client.get(f"{POSTS}/{post_id}")
    assert response.status_code == 200, response.text
    return [part["media"] for part in response.json()["text"]["parts"]]


async def test_an_image_attached_to_a_draft_shows_on_its_part(client, subscribed, post_with):
    post_id = await post_with("Look at this.")

    response = await _attach(client, post_id, png(40, 30))

    assert response.status_code == 201, response.text
    media = response.json()
    assert media["id"].startswith("media_")
    assert media == {
        "id": media["id"],
        "kind": "image",
        "preview_url": f"/media/{media['id']}/preview",
        "width": 40,
        "height": 30,
    }
    assert await _media_of(client, post_id) == [[media]]


async def test_jpeg_and_webp_images_are_taken_too(client, subscribed, post_with):
    post_id = await post_with("Two formats.")

    first = await _attach(client, post_id, jpeg(), name="a.jpg", content_type="image/jpeg")
    second = await _attach(client, post_id, webp(), name="b.webp", content_type="image/webp")

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert [m["id"] for m in (await _media_of(client, post_id))[0]] == [
        first.json()["id"],
        second.json()["id"],
    ]


async def test_each_part_of_a_thread_holds_its_own_media(client, subscribed, post_with):
    post_id = await post_with("One.", "Two.", "Three.")

    attached = await _attach(client, post_id, png(), part=2)

    assert attached.status_code == 201, attached.text
    assert await _media_of(client, post_id) == [[], [attached.json()], []]


async def test_the_type_comes_from_the_bytes_not_the_name(client, subscribed, post_with):
    post_id = await post_with("Sneaky.")

    response = await _attach(
        client, post_id, b"plain text, not an image", name="photo.png", content_type="image/png"
    )

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "Pumpkit takes JPEG, PNG or WEBP images.",
        "code": "MEDIA_TYPE_UNSUPPORTED",
    }
    assert await _media_of(client, post_id) == [[]]


async def test_a_gif_is_not_taken_yet(client, subscribed, post_with):
    post_id = await post_with("Animated.")

    response = await _attach(client, post_id, gif(), name="loop.gif", content_type="image/gif")

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "MEDIA_TYPE_UNSUPPORTED"


async def test_an_image_over_5_mb_is_refused(client, subscribed, post_with):
    post_id = await post_with("Heavy.")

    response = await _attach(client, post_id, padded(png(), 5 * MB + 1))

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "This image is larger than 5 MB, the most X takes.",
        "code": "MEDIA_TOO_LARGE",
    }
    assert await _media_of(client, post_id) == [[]]


async def test_an_oversize_upload_is_refused_while_it_streams(client, subscribed, post_with):
    post_id = await post_with("Endless.")
    sent = 0

    async def endless_image() -> AsyncIterator[bytes]:
        nonlocal sent
        for chunk in _file_head(png()):
            sent += len(chunk)
            yield chunk
        # With no Content-Length, nothing says how large the file is until it ends.
        while sent < 50 * MB:
            sent += 64 * 1024
            yield b"\0" * (64 * 1024)
        yield FILE_END

    response = await _stream(client, post_id, endless_image())

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "MEDIA_TOO_LARGE"
    assert sent < 6 * MB
    assert await _media_of(client, post_id) == [[]]


async def test_uploads_past_the_rate_are_refused_before_the_file_is_read(
    client, subscribed, post_with
):
    post_id = await post_with("Busy.")
    for _ in range(60):
        # A Part the Text doesn't have: refused, but counted.
        assert (await _attach(client, post_id, png(), part=2)).status_code == 404
    sent = 0

    async def image() -> AsyncIterator[bytes]:
        nonlocal sent
        for chunk in [*_file_head(padded(png(), 4 * MB)), FILE_END]:
            sent += len(chunk)
            yield chunk

    response = await _stream(client, post_id, image())

    assert response.status_code == 429, response.text
    assert sent < MB
    assert await _media_of(client, post_id) == [[]]


async def test_no_database_connection_is_held_while_the_file_arrives(
    client, subscribed, post_with, db_engine
):
    post_id = await post_with("Slow.")
    held = 0

    def checked_out(*_args) -> None:
        nonlocal held
        held += 1

    def checked_in(*_args) -> None:
        nonlocal held
        held -= 1

    event.listen(db_engine.sync_engine, "checkout", checked_out)
    event.listen(db_engine.sync_engine, "checkin", checked_in)
    held_before = held
    held_while_streaming: list[int] = []

    async def slow_image() -> AsyncIterator[bytes]:
        for chunk in _file_head(png()):
            yield chunk
            held_while_streaming.append(held)
        yield FILE_END

    response = await _stream(client, post_id, slow_image())

    assert response.status_code == 201, response.text
    assert held_while_streaming
    assert set(held_while_streaming) == {held_before}


async def test_an_upload_without_a_file_is_refused(client, subscribed, post_with):
    post_id = await post_with("Empty-handed.")

    response = await client.post(
        f"{POSTS}/{post_id}/text/parts/1/media", files={"other": ("a.png", png(), "image/png")}
    )

    assert response.status_code == 400, response.text
    assert await _media_of(client, post_id) == [[]]


async def test_an_image_of_exactly_5_mb_is_taken(client, subscribed, post_with):
    post_id = await post_with("Just fits.")

    response = await _attach(client, post_id, padded(png(), 5 * MB))

    assert response.status_code == 201, response.text


async def test_a_file_that_only_starts_like_an_image_is_refused(client, subscribed, post_with):
    post_id = await post_with("Broken.")

    response = await _attach(client, post_id, png()[:24] + b"not the rest of a png")

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "MEDIA_UNREADABLE"


@pytest.mark.parametrize(
    "error",
    [struct.error("bad EXIF"), KeyError(274), TypeError("bad tag"), IndexError(), EOFError()],
)
async def test_an_image_whose_metadata_breaks_the_reader_is_unreadable(
    client, subscribed, post_with, monkeypatch, error
):
    post_id = await post_with("Odd EXIF.")

    def broken_metadata(image):
        raise error

    monkeypatch.setattr(media_files.ImageOps, "exif_transpose", broken_metadata)

    response = await _attach(client, post_id, png())

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "MEDIA_UNREADABLE"
    assert await _media_of(client, post_id) == [[]]


async def test_a_fifth_image_on_a_part_is_refused_naming_the_part(client, subscribed, post_with):
    post_id = await post_with("One.", "Two.")
    for _ in range(4):
        assert (await _attach(client, post_id, png(), part=2)).status_code == 201

    response = await _attach(client, post_id, png(), part=2)

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "Part 2 holds 4 images already. "
        "X takes up to 4 images, or 1 GIF, or 1 video, per post.",
        "code": "MEDIA_PART_FULL",
    }
    assert [len(media) for media in await _media_of(client, post_id)] == [0, 4]


async def test_a_full_single_post_is_named_as_the_post(client, subscribed, post_with):
    post_id = await post_with("Only one.")
    for _ in range(4):
        await _attach(client, post_id, png())

    response = await _attach(client, post_id, png())

    assert response.json()["detail"].startswith("This post holds 4 images already.")


async def test_a_part_the_text_does_not_have_is_not_found(client, subscribed, post_with):
    post_id = await post_with("One.", "Two.")

    response = await _attach(client, post_id, png(), part=3)

    assert response.status_code == 404, response.text


async def test_removing_media_leaves_the_rest_in_order(client, subscribed, post_with):
    post_id = await post_with("Three pictures.")
    ids = [(await _attach(client, post_id, png())).json()["id"] for _ in range(3)]

    response = await client.delete(f"{POSTS}/{post_id}/text/media/{ids[1]}")

    assert response.status_code == 204, response.text
    assert [m["id"] for m in (await _media_of(client, post_id))[0]] == [ids[0], ids[2]]


async def test_a_removed_image_makes_room_for_another(client, subscribed, post_with):
    post_id = await post_with("Full, then not.")
    ids = [(await _attach(client, post_id, png())).json()["id"] for _ in range(4)]
    await client.delete(f"{POSTS}/{post_id}/text/media/{ids[0]}")

    response = await _attach(client, post_id, png())

    assert response.status_code == 201, response.text
    assert [m["id"] for m in (await _media_of(client, post_id))[0]] == [
        *ids[1:],
        response.json()["id"],
    ]


async def test_removing_media_the_text_does_not_hold_is_not_found(client, subscribed, post_with):
    post_id = await post_with("Nothing here.")

    response = await client.delete(f"{POSTS}/{post_id}/text/media/media_unknown")

    assert response.status_code == 404, response.text


async def test_editing_the_text_keeps_its_media(client, subscribed, post_with):
    post_id = await post_with("Before.")
    attached = (await _attach(client, post_id, png())).json()

    response = await client.put(f"{POSTS}/{post_id}/text", json={"parts": ["After."]})

    assert response.status_code == 200, response.text
    assert response.json()["parts"][0]["media"] == [attached]


async def test_another_users_post_takes_no_media(
    client, subscribed, post_with, sign_in_as_another_subscribed_user
):
    post_id = await post_with("Mine.")
    attached = (await _attach(client, post_id, png())).json()
    await sign_in_as_another_subscribed_user()

    attach = await _attach(client, post_id, png())
    remove = await client.delete(f"{POSTS}/{post_id}/text/media/{attached['id']}")

    assert attach.status_code == 404, attach.text
    assert remove.status_code == 404, remove.text


async def test_a_scheduled_posts_text_takes_no_media(
    client, subscribed, fixed_clock, post_with, connect_x
):
    await connect_x()
    post_id = await post_with("Set to go.")
    attached = (await _attach(client, post_id, png())).json()
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})
    assert scheduled.status_code == 201, scheduled.text

    attach = await _attach(client, post_id, png())
    remove = await client.delete(f"{POSTS}/{post_id}/text/media/{attached['id']}")

    assert attach.status_code == 409, attach.text
    assert remove.status_code == 409, remove.text


async def test_a_failed_posts_part_already_on_x_keeps_its_media(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Live one.", "Refused two.")
    live = (await _attach(client, post_id, png(), part=1)).json()
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = 2
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert scheduled.json()["state"] == "failed", scheduled.text

    attach = await _attach(client, post_id, png(), part=1)
    remove = await client.delete(f"{POSTS}/{post_id}/text/media/{live['id']}")
    on_refused_part = await _attach(client, post_id, png(), part=2)

    assert attach.status_code == 409, attach.text
    assert attach.json()["detail"] == "Part 1 is already on X, so its media is set."
    assert remove.status_code == 409, remove.text
    assert on_refused_part.status_code == 201, on_refused_part.text
    assert await _media_of(client, post_id) == [[live], [on_refused_part.json()]]


async def _connect_x_before_media(db, connect_x) -> None:
    """An X connection made before Pumpkit asked X for `media.write`."""
    await connect_x()
    await db.execute(
        update(XConnection).values(scopes="tweet.read tweet.write users.read offline.access")
    )
    await db.commit()


async def test_an_x_connection_without_media_write_is_asked_to_reconnect_before_the_file_is_read(
    client, db, subscribed, fixed_clock, connect_x, post_with
):
    await _connect_x_before_media(db, connect_x)
    post_id = await post_with("Old connection.")
    sent = 0

    async def image() -> AsyncIterator[bytes]:
        nonlocal sent
        for chunk in [*_file_head(padded(png(), 4 * MB)), FILE_END]:
            sent += len(chunk)
            yield chunk

    response = await _stream(client, post_id, image())

    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": "Reconnect X so Pumpkit can post media on your X account.",
        "code": "X_RECONNECT_FOR_MEDIA",
        "url": "http://localhost:5173/settings",
    }
    assert sent < MB
    assert await _media_of(client, post_id) == [[]]


async def test_reconnecting_x_lets_media_be_attached(
    client, db, subscribed, fixed_clock, connect_x, post_with
):
    await _connect_x_before_media(db, connect_x)
    post_id = await post_with("Reconnected.")

    await connect_x()
    response = await _attach(client, post_id, png())

    assert response.status_code == 201, response.text


async def test_without_an_x_connection_media_is_attached(client, subscribed, post_with):
    post_id = await post_with("Not connected yet.")

    response = await _attach(client, post_id, png())

    assert response.status_code == 201, response.text
    assert await _media_of(client, post_id) == [[response.json()]]
