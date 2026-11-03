"""
The `attach_media` and `remove_media` MCP tools and the Media `get_post` lists: an AI app
attaches an image from a public URL to the Post's Text, or to its waiting Scheduled post's own
copy, with the web upload's checks and refusals.
"""

import pytest
from sqlalchemy import update

from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.mcp_client import error_text
from tests.media_files import MB, image, padded, png

POSTS_PAGE = "http://localhost:5173/posts"
SETTINGS_PAGE = "http://localhost:5173/settings"
IMAGE_URL = "https://images.example.com/chart.png"


async def _media_through_mcp(mcp, post_id: str) -> list[list[dict]]:
    read = await mcp.call_tool("get_post", post_id=post_id)
    assert read["isError"] is False, read
    return [part["media"] for part in read["structuredContent"]["text"]["parts"]]


async def test_an_image_from_a_url_is_attached_to_the_drafts_part_with_its_alt_text(
    subscribed, mcp, post_with, fake_media_url_fetcher
):
    post_id = await post_with("One", "Two")
    fake_media_url_fetcher.serve(IMAGE_URL, png(40, 30))

    result = await mcp.call_tool(
        "attach_media", post_id=post_id, part=2, url=IMAGE_URL, alt_text="A rising line."
    )

    assert result["isError"] is False, result
    attached = result["structuredContent"]
    media = attached["media"]
    assert media["kind"] == "image"
    assert media["alt_text"] == "A rising line."
    assert (media["width"], media["height"]) == (40, 30)
    assert attached["post_url"] == f"{POSTS_PAGE}/{post_id}"
    assert await _media_through_mcp(mcp, post_id) == [[], [media]]
    assert fake_media_url_fetcher.fetched == [IMAGE_URL]


async def test_a_url_that_cant_be_downloaded_is_refused(
    subscribed, mcp, post_with, fake_media_url_fetcher
):
    post_id = await post_with("One")

    result = await mcp.call_tool("attach_media", post_id=post_id, url=IMAGE_URL)

    assert "couldn't download" in error_text(result)
    assert result["structuredContent"]["code"] == "MEDIA_URL_UNREACHABLE"
    assert await _media_through_mcp(mcp, post_id) == [[]]


async def _attach(mcp, fake_media_url_fetcher, post_id: str, data: bytes, **arguments) -> dict:
    url = f"https://images.example.com/{len(fake_media_url_fetcher.files)}.png"
    fake_media_url_fetcher.serve(url, data)
    return await mcp.call_tool("attach_media", post_id=post_id, url=url, **arguments)


async def _attached(mcp, fake_media_url_fetcher, post_id: str, **arguments) -> dict:
    result = await _attach(mcp, fake_media_url_fetcher, post_id, png(), **arguments)
    assert result["isError"] is False, result
    return result["structuredContent"]["media"]


async def _schedule(mcp, post_id: str) -> dict:
    scheduled = await mcp.call_tool(
        "schedule_post", post_id=post_id, publish_at="2026-10-10T16:00:00+02:00"
    )
    assert scheduled["isError"] is False, scheduled
    return scheduled["structuredContent"]


async def _scheduled_post_media(mcp, post_id: str) -> list[list[dict]]:
    read = await mcp.call_tool("get_post", post_id=post_id)
    return [part["media"] for part in read["structuredContent"]["scheduled_post"]["parts"]]


@pytest.fixture
async def connected(subscribed, fixed_clock, connect_x) -> None:
    await connect_x()


async def test_attaching_on_a_scheduled_post_changes_the_scheduled_posts_copy_not_the_text(
    connected, mcp, post_with, fake_media_url_fetcher
):
    post_id = await post_with("One", "Two")
    on_text = await _attached(mcp, fake_media_url_fetcher, post_id)
    await _schedule(mcp, post_id)

    attached = await _attach(mcp, fake_media_url_fetcher, post_id, png(), part=2)

    assert attached["isError"] is False, attached
    added = attached["structuredContent"]["media"]
    assert attached["structuredContent"]["message"] == (
        "Attached to part 2 of the post's scheduled post."
    )
    assert await _scheduled_post_media(mcp, post_id) == [[on_text], [added]]
    assert await _media_through_mcp(mcp, post_id) == [[on_text], []]


async def test_removing_on_a_scheduled_post_changes_the_scheduled_posts_copy_not_the_text(
    connected, mcp, post_with, fake_media_url_fetcher
):
    post_id = await post_with("One")
    on_text = await _attached(mcp, fake_media_url_fetcher, post_id)
    await _schedule(mcp, post_id)

    removed = await mcp.call_tool("remove_media", post_id=post_id, media_id=on_text["id"])

    assert removed["isError"] is False, removed
    assert removed["structuredContent"]["message"] == "Removed from the post's scheduled post."
    assert await _scheduled_post_media(mcp, post_id) == [[]]
    assert await _media_through_mcp(mcp, post_id) == [[on_text]]


async def test_remove_media_takes_media_off_a_drafts_text(
    subscribed, mcp, post_with, fake_media_url_fetcher
):
    post_id = await post_with("One")
    first = await _attached(mcp, fake_media_url_fetcher, post_id)
    second = await _attached(mcp, fake_media_url_fetcher, post_id)

    removed = await mcp.call_tool("remove_media", post_id=post_id, media_id=first["id"])

    assert removed["isError"] is False, removed
    assert removed["structuredContent"] == {
        "message": "Removed from the post's text.",
        "post_url": f"{POSTS_PAGE}/{post_id}",
    }
    assert await _media_through_mcp(mcp, post_id) == [[second]]
    unknown = await mcp.call_tool("remove_media", post_id=post_id, media_id=first["id"])
    assert error_text(unknown) == "This post's text has no such media."


async def test_on_a_failed_post_media_changes_the_text_but_not_a_part_already_on_x(
    connected, mcp, post_with, fake_media_url_fetcher, fake_x_publisher
):
    post_id = await post_with("One", "Two")
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = 2
    failed = await mcp.call_tool("post_now", post_id=post_id)
    assert failed["structuredContent"]["state"] == "failed", failed

    on_live = await _attach(mcp, fake_media_url_fetcher, post_id, png(), part=1)
    assert error_text(on_live) == "Part 1 is already on X, so its media is set."
    assert fake_media_url_fetcher.fetched == []
    attached = await _attach(mcp, fake_media_url_fetcher, post_id, png(), part=2)

    assert attached["isError"] is False, attached
    assert attached["structuredContent"]["message"] == "Attached to part 2 of the post's text."
    assert await _media_through_mcp(mcp, post_id) == [[], [attached["structuredContent"]["media"]]]


async def test_a_published_post_keeps_its_media(connected, mcp, post_with, fake_media_url_fetcher):
    post_id = await post_with("Gone out.")
    on_text = await _attached(mcp, fake_media_url_fetcher, post_id)
    published = await mcp.call_tool("post_now", post_id=post_id)
    assert published["structuredContent"]["state"] == "published", published
    downloaded = len(fake_media_url_fetcher.fetched)

    attached = await _attach(mcp, fake_media_url_fetcher, post_id, png())
    removed = await mcp.call_tool("remove_media", post_id=post_id, media_id=on_text["id"])

    refusal = "This post is published, so its text is set. Start a new post to write another."
    assert error_text(attached) == refusal
    assert error_text(removed) == refusal
    assert len(fake_media_url_fetcher.fetched) == downloaded


async def test_files_the_web_upload_refuses_are_refused_in_its_words(
    subscribed, mcp, post_with, fake_media_url_fetcher
):
    post_id = await post_with("One")

    too_large = await _attach(mcp, fake_media_url_fetcher, post_id, padded(png(), 5 * MB + 1))
    a_bmp = await _attach(mcp, fake_media_url_fetcher, post_id, image("BMP"))
    unreadable = await _attach(mcp, fake_media_url_fetcher, post_id, png()[:40])

    assert error_text(too_large) == "This image is larger than 5 MB, the most X takes."
    assert too_large["structuredContent"]["code"] == "MEDIA_TOO_LARGE"
    assert (
        error_text(a_bmp) == "Pumpkit takes JPEG, PNG, WEBP or GIF images, and MP4 or MOV videos."
    )
    assert a_bmp["structuredContent"]["code"] == "MEDIA_TYPE_UNSUPPORTED"
    assert unreadable["structuredContent"]["code"] == "MEDIA_UNREADABLE"
    assert await _media_through_mcp(mcp, post_id) == [[]]


async def test_a_part_holding_four_images_is_refused_another(
    subscribed, mcp, post_with, fake_media_url_fetcher
):
    post_id = await post_with("Four already.")
    for _ in range(4):
        await _attached(mcp, fake_media_url_fetcher, post_id)
    downloaded = len(fake_media_url_fetcher.fetched)

    full = await _attach(mcp, fake_media_url_fetcher, post_id, png())

    assert error_text(full) == (
        "This post holds 4 images already. X takes up to 4 images, or 1 GIF, or 1 video, per post."
    )
    assert full["structuredContent"]["code"] == "MEDIA_PART_FULL"
    assert len(fake_media_url_fetcher.fetched) == downloaded


async def test_a_part_the_post_doesnt_have_is_refused_before_downloading(
    subscribed, mcp, post_with, fake_media_url_fetcher
):
    post_id = await post_with("One")

    result = await _attach(mcp, fake_media_url_fetcher, post_id, png(), part=2)

    assert error_text(result) == "This post's text has no part 2."
    assert fake_media_url_fetcher.fetched == []


async def test_an_x_connection_without_media_write_is_asked_to_reconnect_before_downloading(
    db, subscribed, fixed_clock, connect_x, mcp, post_with, fake_media_url_fetcher
):
    await connect_x()
    await db.execute(
        update(XConnection).values(scopes="tweet.read tweet.write users.read offline.access")
    )
    await db.commit()
    post_id = await post_with("Old connection.")

    result = await _attach(mcp, fake_media_url_fetcher, post_id, png())

    assert error_text(result) == (
        f"Reconnect X so Pumpkit can post media on your X account. {SETTINGS_PAGE}"
    )
    assert result["structuredContent"]["code"] == "X_RECONNECT_FOR_MEDIA"
    assert fake_media_url_fetcher.fetched == []


async def test_alt_text_past_x_s_limit_is_refused(
    subscribed, mcp, post_with, fake_media_url_fetcher
):
    post_id = await post_with("One")

    result = await _attach(mcp, fake_media_url_fetcher, post_id, png(), alt_text="a" * 1001)

    assert error_text(result) == "Alt text can be up to 1,000 characters."
    assert fake_media_url_fetcher.fetched == []


async def test_alt_text_is_stripped_before_its_length_is_checked(
    subscribed, mcp, post_with, fake_media_url_fetcher
):
    post_id = await post_with("One")

    media = await _attached(mcp, fake_media_url_fetcher, post_id, alt_text=f"  {'a' * 1000}\n")

    assert media["alt_text"] == "a" * 1000


async def test_attaching_and_removing_media_use_no_generation(
    subscribed, mcp, post_with, fake_media_url_fetcher
):
    post_id = await post_with("One")
    before = await mcp.call_tool("get_usage")

    attached = await _attached(mcp, fake_media_url_fetcher, post_id)
    await mcp.call_tool("remove_media", post_id=post_id, media_id=attached["id"])

    after = await mcp.call_tool("get_usage")
    assert after["structuredContent"]["allowance"] == before["structuredContent"]["allowance"]


async def test_recopying_the_text_copies_its_media_to_the_scheduled_post(
    connected, mcp, post_with, fake_media_url_fetcher
):
    post_id = await post_with("One")
    scheduled = await _schedule(mcp, post_id)
    await mcp.call_tool("delete_scheduled_post", scheduled_post_id=scheduled["id"])
    attached = await _attached(mcp, fake_media_url_fetcher, post_id)
    rescheduled = await _schedule(mcp, post_id)
    removed = await mcp.call_tool("remove_media", post_id=post_id, media_id=attached["id"])
    assert removed["isError"] is False, removed
    assert await _scheduled_post_media(mcp, post_id) == [[]]

    recopied = await mcp.call_tool(
        "edit_scheduled_post", scheduled_post_id=rescheduled["id"], copy_text=True
    )

    assert recopied["isError"] is False, recopied
    assert await _scheduled_post_media(mcp, post_id) == [[attached]]


async def test_the_server_instructions_say_media_goes_out_as_given_and_is_never_read(
    subscribed, mcp
):
    instructions = (await mcp.initialize())["instructions"]

    assert "publishes media exactly as given" in instructions
    assert "its writing never reads it" in instructions
