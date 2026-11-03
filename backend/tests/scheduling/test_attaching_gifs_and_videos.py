"""
Attaching an animated GIF or a video to a Part through the same upload routes as images
(ADR 0021): kinds are told by the file's bytes, each has its own limit, and one X post takes
up to 4 images, or 1 GIF, or 1 video. The web app sends a video's length and first frame with it.
"""

from collections.abc import AsyncIterator
from io import BytesIO

import pytest
from httpx import AsyncClient
from PIL import Image

from tests.media_files import MB, animated_gif, jpeg, mov, mp4, padded, png

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
    name: str = "clip.mp4",
    content_type: str = "video/mp4",
    duration_ms: str | None = None,
    poster: bytes | None = None,
):
    files = {"file": (name, data, content_type)}
    if poster is not None:
        files = {"poster": ("poster.jpg", poster, "image/jpeg"), **files}
    return await client.post(
        f"{POSTS}/{post_id}/text/parts/{part}/media",
        files=files,
        data={"duration_ms": duration_ms} if duration_ms is not None else None,
    )


async def _gif(client: AsyncClient, post_id: str, data: bytes | None = None, *, part: int = 1):
    return await _attach(
        client,
        post_id,
        data if data is not None else animated_gif(),
        part=part,
        name="loop.gif",
        content_type="image/gif",
    )


async def _png(client: AsyncClient, post_id: str, *, part: int = 1):
    return await _attach(
        client, post_id, png(), part=part, name="photo.png", content_type="image/png"
    )


async def _media_of(client: AsyncClient, post_id: str) -> list[list[dict]]:
    response = await client.get(f"{POSTS}/{post_id}")
    assert response.status_code == 200, response.text
    return [part["media"] for part in response.json()["text"]["parts"]]


async def test_an_animated_gif_is_attached_as_a_gif(client, subscribed, post_with):
    post_id = await post_with("A loop.")

    response = await _gif(client, post_id, animated_gif(width=48, height=24))

    assert response.status_code == 201, response.text
    media = response.json()
    assert media == {
        "id": media["id"],
        "kind": "gif",
        "preview_url": f"/media/{media['id']}/preview",
        "width": 48,
        "height": 24,
        "alt_text": None,
        "duration_ms": None,
    }
    preview = await client.get(f"/api/v1{media['preview_url']}")
    assert preview.status_code == 200, preview.text
    assert Image.open(BytesIO(preview.content)).size == (48, 24)
    assert await _media_of(client, post_id) == [[media]]


async def test_a_gif_of_15_mb_is_taken_and_a_larger_one_refused(client, subscribed, post_with):
    post_id = await post_with("Heavy loops.", "Heavier.")

    taken = await _gif(client, post_id, padded(animated_gif(), 15 * MB))
    refused = await _gif(client, post_id, padded(animated_gif(), 15 * MB + 1), part=2)

    assert taken.status_code == 201, taken.text
    assert refused.status_code == 422, refused.text
    assert refused.json() == {
        "detail": "This GIF is larger than 15 MB, the most X takes.",
        "code": "MEDIA_TOO_LARGE",
    }


async def test_a_video_comes_with_the_length_and_first_frame_the_browser_read(
    client, subscribed, post_with
):
    post_id = await post_with("A demo.")

    response = await _attach(
        client, post_id, mp4(), duration_ms="42500", poster=jpeg(width=64, height=36)
    )

    assert response.status_code == 201, response.text
    media = response.json()
    assert media == {
        "id": media["id"],
        "kind": "video",
        "preview_url": f"/media/{media['id']}/preview",
        "width": 64,
        "height": 36,
        "alt_text": None,
        "duration_ms": 42500,
    }
    preview = await client.get(f"/api/v1{media['preview_url']}")
    assert Image.open(BytesIO(preview.content)).size == (64, 36)
    original = await client.get(f"/api/v1/media/{media['id']}/file")
    assert original.content == mp4()
    assert await _media_of(client, post_id) == [[media]]


async def test_a_video_sent_alone_has_no_preview_and_no_length(client, subscribed, post_with):
    post_id = await post_with("From an iPhone.")

    response = await _attach(client, post_id, mov(), name="IMG_0001.MOV", content_type="")

    assert response.status_code == 201, response.text
    media = response.json()
    assert (media["kind"], media["preview_url"], media["duration_ms"]) == ("video", None, None)
    assert (media["width"], media["height"]) == (None, None)


async def test_a_first_frame_that_is_no_image_leaves_the_video_without_a_preview(
    client, subscribed, post_with
):
    post_id = await post_with("Odd poster.")

    response = await _attach(client, post_id, mp4(), poster=b"not an image at all")

    assert response.status_code == 201, response.text
    assert response.json()["preview_url"] is None


@pytest.mark.parametrize("duration_ms", ["soon", "-1", "1.5", "86400001", "9999999999999999"])
async def test_a_length_that_is_no_count_of_milliseconds_up_to_a_day_is_refused(
    client, subscribed, post_with, duration_ms
):
    post_id = await post_with("Bad length.")

    response = await _attach(client, post_id, mp4(), duration_ms=duration_ms)

    assert response.status_code == 400, response.text
    assert await _media_of(client, post_id) == [[]]


async def test_an_upload_with_an_unknown_field_is_refused(client, subscribed, post_with):
    post_id = await post_with("Extra.")

    response = await client.post(
        f"{POSTS}/{post_id}/text/parts/1/media",
        files={"file": ("clip.mp4", mp4(), "video/mp4")},
        data={"caption": "hello"},
    )

    assert response.status_code == 400, response.text


@pytest.mark.parametrize(
    "head",
    [
        b"\0\0\0\x18ftypisom\0\0\x02\0isomiso2avc1mp41",
        b"\0\0\0\x18ftypavc1\0\0\0\0avc1isom",
        b"\0\0\0\x18ftypM4V \0\0\0\x01M4V mp42",
        b"\0\0\0\x08wide\0\0\x10\0mdat",
        b"\0\0\x10\0mdat",
        b"\0\0\x10\0moov",
    ],
    ids=["isom", "avc1", "m4v", "wide-then-mdat", "mdat", "moov"],
)
async def test_mp4_and_quicktime_videos_by_their_first_box_are_taken(
    client, subscribed, post_with, head
):
    post_id = await post_with("A video.")

    response = await _attach(client, post_id, padded(head, 64))

    assert response.status_code == 201, response.text
    assert response.json()["kind"] == "video"


@pytest.mark.parametrize(
    "head",
    [
        b"\0\0\0\x18ftypheic\0\0\0\0mif1heic",
        b"\0\0\0\x1cftypavif\0\0\0\0avifmif1",
        b"\0\0\0\x20ftypM4A \0\0\0\0M4A isom",
        b"\0\0\0\x20ftypf4a \0\0\0\0isommp42",
        b"\0\0\0\x14ftypmjp2\0\0\0\0mjp2",
        b"\0\0\0\x18ftyp3gp4\0\0\0\0isom3gp4",
        b"\0\0\0\x08freeNot a movie at all",
        b"\0\0\x10\0wideNot a movie",
        b"\0\0\0\x08skip\0\0\0\x08junk",
    ],
    ids=["heic", "avif", "m4a", "f4a", "motion-jpeg-2000", "3gp", "free", "wide", "skip"],
)
async def test_other_files_that_look_like_mp4_are_refused(client, subscribed, post_with, head):
    post_id = await post_with("Not a video.")

    response = await _attach(client, post_id, padded(head, 64))

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "Pumpkit takes JPEG, PNG, WEBP or GIF images, and MP4 or MOV videos.",
        "code": "MEDIA_TYPE_UNSUPPORTED",
    }


async def test_a_video_over_512_mb_is_refused_while_it_streams(client, subscribed, post_with):
    post_id = await post_with("Too long.")
    sent = 0
    chunk = b"\0" * MB

    async def endless_video() -> AsyncIterator[bytes]:
        nonlocal sent
        for part in [
            b"--" + BOUNDARY + b"\r\n",
            b'Content-Disposition: form-data; name="file"; filename="clip.mp4"\r\n',
            b"Content-Type: video/mp4\r\n\r\n",
            mp4(),
        ]:
            sent += len(part)
            yield part
        while sent < 600 * MB:
            sent += len(chunk)
            yield chunk
        yield b"\r\n--" + BOUNDARY + b"--\r\n"

    response = await client.post(
        f"{POSTS}/{post_id}/text/parts/1/media",
        content=endless_video(),
        headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY.decode()}"},
    )

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "This video is larger than 512 MB, the most X takes.",
        "code": "MEDIA_TOO_LARGE",
    }
    assert sent < 514 * MB
    assert await _media_of(client, post_id) == [[]]


X_RULE = "X takes up to 4 images, or 1 GIF, or 1 video, per post."


async def test_a_part_holding_a_gif_takes_nothing_more(client, subscribed, post_with):
    post_id = await post_with("One.", "Two.")
    assert (await _gif(client, post_id, part=2)).status_code == 201

    image = await _png(client, post_id, part=2)
    second_gif = await _gif(client, post_id, part=2)

    for refused in (image, second_gif):
        assert refused.status_code == 422, refused.text
        assert refused.json() == {
            "detail": f"Part 2 holds a GIF already. {X_RULE}",
            "code": "MEDIA_PART_FULL",
        }
    assert [len(media) for media in await _media_of(client, post_id)] == [0, 1]


async def test_a_post_holding_a_video_takes_nothing_more(client, subscribed, post_with):
    post_id = await post_with("Only one.")
    assert (await _attach(client, post_id, mp4())).status_code == 201

    response = await _png(client, post_id)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == f"This post holds a video already. {X_RULE}"


async def test_a_part_holding_images_takes_no_gif_or_video(client, subscribed, post_with):
    post_id = await post_with("Pictures.")
    assert (await _png(client, post_id)).status_code == 201

    gif = await _gif(client, post_id)
    video = await _attach(client, post_id, mp4())

    for refused in (gif, video):
        assert refused.status_code == 422, refused.text
        assert refused.json() == {
            "detail": f"This post holds images already. {X_RULE}",
            "code": "MEDIA_PART_FULL",
        }
    assert [m["kind"] for m in (await _media_of(client, post_id))[0]] == ["image"]


async def test_a_gif_takes_alt_text_and_a_video_does_not(client, subscribed, post_with):
    post_id = await post_with("Gif.", "Video.")
    gif = (await _gif(client, post_id)).json()
    video = (await _attach(client, post_id, mp4(), part=2)).json()

    described = await client.put(
        f"{POSTS}/{post_id}/text/media/{gif['id']}/alt-text", json={"alt_text": "A cat spins."}
    )
    refused = await client.put(
        f"{POSTS}/{post_id}/text/media/{video['id']}/alt-text", json={"alt_text": "A demo."}
    )

    assert described.json()["alt_text"] == "A cat spins."
    assert refused.status_code == 422, refused.text


async def test_a_waiting_scheduled_post_takes_a_video_on_its_own_part(
    client, subscribed, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("One.", "Two.")
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})
    scheduled_post_id = scheduled.json()["id"]

    video = await client.post(
        f"{SCHEDULED_POSTS}/{scheduled_post_id}/parts/2/media",
        files={"file": ("clip.mp4", mp4(), "video/mp4")},
        data={"duration_ms": "9000"},
    )
    image = await client.post(
        f"{SCHEDULED_POSTS}/{scheduled_post_id}/parts/2/media",
        files={"file": ("photo.png", png(), "image/png")},
    )

    assert video.status_code == 201, video.text
    assert video.json()["duration_ms"] == 9000
    assert image.status_code == 422, image.text
    assert image.json()["detail"] == f"Part 2 holds a video already. {X_RULE}"
