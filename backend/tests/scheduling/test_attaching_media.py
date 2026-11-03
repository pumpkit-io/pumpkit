"""
Attaching Media to a Post's Text and removing it, through
`POST /posts/{id}/text/parts/{n}/media` and `DELETE /posts/{id}/text/media/{media_id}`, and
reading it back on `GET /posts/{id}` (ADR 0021). Only a Draft or a Failed Post's Text takes it.
"""

from httpx import AsyncClient

from tests.media_files import MB, gif, jpeg, padded, png, webp

POSTS = "/api/v1/posts"


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


async def test_an_image_of_exactly_5_mb_is_taken(client, subscribed, post_with):
    post_id = await post_with("Just fits.")

    response = await _attach(client, post_id, padded(png(), 5 * MB))

    assert response.status_code == 201, response.text


async def test_a_file_that_only_starts_like_an_image_is_refused(client, subscribed, post_with):
    post_id = await post_with("Broken.")

    response = await _attach(client, post_id, png()[:24] + b"not the rest of a png")

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "MEDIA_UNREADABLE"


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


async def test_a_scheduled_posts_text_takes_no_media(client, subscribed, post_with, connect_x):
    await connect_x()
    post_id = await post_with("Set to go.")
    attached = (await _attach(client, post_id, png())).json()
    scheduled = await client.post(
        "/api/v1/scheduled-posts", json={"post_id": post_id, "publish_at": "2026-12-10T14:00:00Z"}
    )
    assert scheduled.status_code == 201, scheduled.text

    attach = await _attach(client, post_id, png())
    remove = await client.delete(f"{POSTS}/{post_id}/text/media/{attached['id']}")

    assert attach.status_code == 409, attach.text
    assert remove.status_code == 409, remove.text
