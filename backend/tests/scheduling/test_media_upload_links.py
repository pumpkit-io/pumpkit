"""
`attach_media` without a URL: a one-time upload link, bound to the User, Post and Part, that an
app with a shell sends a local image to with the `curl` command the tool answers with. The link
takes the file with no other credentials, once, before it expires.
"""

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
from sqlalchemy import update

import pumpkit.scheduling.publisher as publisher
from pumpkit.auth.models import User
from pumpkit.billing.models import Subscription
from pumpkit.posts.media_files import IMAGE_MAX_BYTES
from pumpkit.posts.schemas import MEDIA_RATE
from pumpkit.x_connection.models import XConnection
from tests.mcp_client import error_text
from tests.media_files import gif, padded, png

POSTS_PAGE = "http://localhost:5173/posts"
SETTINGS_PAGE = "http://localhost:5173/settings"
UPLOADS = "http://localhost:5173/api/v1/media-uploads/"
CONNECTIONS = "/api/v1/app-connections"
MEDIA_PER_MINUTE = int(MEDIA_RATE.split("/")[0])


async def _link(mcp, post_id: str, **arguments) -> dict:
    result = await mcp.call_tool("attach_media", post_id=post_id, **arguments)
    assert result["isError"] is False, result
    return result["structuredContent"]


async def _upload(new_browser, link: dict, data: bytes, name: str = "chart.png"):
    """Sends `data` the way the link's `curl` command does, from a client with no credentials."""
    path = urlsplit(link["upload_url"]).path
    return await new_browser().post(path, files={"file": (name, data, "application/octet-stream")})


async def _media_of(mcp, post_id: str) -> list[list[dict]]:
    read = await mcp.call_tool("get_post", post_id=post_id)
    return [part["media"] for part in read["structuredContent"]["text"]["parts"]]


async def test_without_a_url_the_tool_answers_a_link_its_expiry_and_a_ready_curl_command(
    subscribed, fixed_clock, mcp, post_with
):
    post_id = await post_with("One")

    link = await _link(mcp, post_id)

    upload_url = link["upload_url"]
    assert upload_url.startswith(UPLOADS)
    assert datetime.fromisoformat(link["upload_expires_at"]) == fixed_clock() + timedelta(
        minutes=15
    )
    assert link["curl_command"] == f"curl -F 'file=@-' '{upload_url}' < IMAGE_PATH"
    page = f"{POSTS_PAGE}/{post_id}"
    assert link["post_url"] == page
    assert link["media"] is None
    assert link["curl_command"] in link["message"]
    assert "within 15 minutes" in link["message"]
    assert page in link["message"]


async def test_the_link_attaches_the_image_to_the_part_named_with_its_alt_text(
    subscribed, mcp, new_browser, post_with
):
    post_id = await post_with("One", "Two")
    link = await _link(mcp, post_id, part=2, alt_text="A rising line.")

    response = await _upload(new_browser, link, png(40, 30))

    assert response.status_code == 201, response.text
    answer = response.json()
    assert answer["message"] == "Attached to part 2 of the post's text."
    assert answer["post_url"] == f"{POSTS_PAGE}/{post_id}"
    media = answer["media"]
    assert (media["kind"], media["width"], media["height"]) == ("image", 40, 30)
    assert media["alt_text"] == "A rising line."
    assert await _media_of(mcp, post_id) == [[], [media]]


async def test_a_second_use_of_the_link_is_refused(subscribed, mcp, new_browser, post_with):
    post_id = await post_with("One")
    link = await _link(mcp, post_id)
    assert (await _upload(new_browser, link, png())).status_code == 201

    again = await _upload(new_browser, link, png())

    assert again.status_code == 410
    assert again.json()["detail"] == (
        "This upload link was used already. Call attach_media again for a new one."
    )
    assert again.json()["code"] == "UPLOAD_LINK_USED"
    assert len((await _media_of(mcp, post_id))[0]) == 1


async def test_a_link_used_after_it_expires_is_refused(
    subscribed, fixed_clock, mcp, new_browser, post_with
):
    post_id = await post_with("One")
    link = await _link(mcp, post_id)
    fixed_clock.advance(timedelta(minutes=15))

    response = await _upload(new_browser, link, png())

    assert response.status_code == 410
    assert response.json()["detail"] == (
        "This upload link expired. Call attach_media again for a new one."
    )
    assert response.json()["code"] == "UPLOAD_LINK_EXPIRED"
    assert await _media_of(mcp, post_id) == [[]]


async def test_an_altered_link_is_not_found(subscribed, mcp, new_browser, post_with):
    post_id = await post_with("One", "Two")
    link = await _link(mcp, post_id)

    altered = {
        "upload_url": link["upload_url"][:-1] + ("A" if link["upload_url"][-1] != "A" else "B")
    }
    response = await _upload(new_browser, altered, png())

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "This isn't a Pumpkit upload link. Call attach_media again for a new one."
    )
    assert await _media_of(mcp, post_id) == [[], []]


async def test_files_the_web_upload_refuses_are_refused_and_spend_the_link(
    subscribed, mcp, new_browser, post_with
):
    post_id = await post_with("One")
    link = await _link(mcp, post_id)

    refused = await _upload(new_browser, link, gif())

    assert refused.status_code == 422
    assert refused.json()["code"] == "MEDIA_TYPE_UNSUPPORTED"
    assert (await _upload(new_browser, link, png())).json()["code"] == "UPLOAD_LINK_USED"
    assert await _media_of(mcp, post_id) == [[]]


async def test_the_upload_takes_only_the_file_field(subscribed, mcp, new_browser, post_with):
    post_id = await post_with("One")
    link = await _link(mcp, post_id)
    path = urlsplit(link["upload_url"]).path

    response = await new_browser().post(path, files={"image": ("chart.png", png(), "image/png")})

    assert response.status_code == 400
    assert response.json()["detail"] == "Send one file, as the `file` field, and nothing else."


@pytest.fixture
async def connected(subscribed, fixed_clock, connect_x) -> None:
    await connect_x()


async def test_on_a_scheduled_post_the_link_attaches_to_the_scheduled_posts_copy(
    connected, mcp, new_browser, post_with
):
    post_id = await post_with("One")
    scheduled = await mcp.call_tool(
        "schedule_post", post_id=post_id, publish_at="2026-10-10T16:00:00+02:00"
    )
    assert scheduled["isError"] is False, scheduled
    link = await _link(mcp, post_id)

    response = await _upload(new_browser, link, png())

    assert response.status_code == 201, response.text
    assert response.json()["message"] == "Attached to part 1 of the post's scheduled post."
    read = await mcp.call_tool("get_post", post_id=post_id)
    assert read["structuredContent"]["scheduled_post"]["parts"][0]["media"] == [
        response.json()["media"]
    ]
    assert await _media_of(mcp, post_id) == [[]]


async def test_a_part_the_post_doesnt_have_gets_no_link(subscribed, mcp, post_with):
    post_id = await post_with("One")

    result = await mcp.call_tool("attach_media", post_id=post_id, part=2)

    assert error_text(result) == "This post's text has no part 2."


async def test_a_post_that_isnt_the_users_gets_no_link(subscribed, mcp):
    result = await mcp.call_tool("attach_media", post_id="no-such-post")

    assert error_text(result) == "Post not found."


async def test_an_x_connection_without_media_write_gets_no_link(
    db, connected, connect_x, mcp, post_with
):
    await db.execute(
        update(XConnection).values(scopes="tweet.read tweet.write users.read offline.access")
    )
    await db.commit()
    post_id = await post_with("Old connection.")

    result = await mcp.call_tool("attach_media", post_id=post_id)

    assert error_text(result) == (
        f"Reconnect X so Pumpkit can post media on your X account. {SETTINGS_PAGE}"
    )


async def test_a_part_filled_since_the_link_was_made_is_refused_before_the_file_and_keeps_it(
    subscribed, mcp, new_browser, post_with
):
    post_id = await post_with("One")
    link = await _link(mcp, post_id)
    for _ in range(4):
        assert (await _upload(new_browser, await _link(mcp, post_id), png())).status_code == 201

    full = await _upload(new_browser, link, png())

    assert full.status_code == 422
    assert full.json()["code"] == "MEDIA_PART_FULL"
    removed = (await _media_of(mcp, post_id))[0][0]
    await mcp.call_tool("remove_media", post_id=post_id, media_id=removed["id"])
    assert (await _upload(new_browser, link, png())).status_code == 201


async def test_a_user_without_a_subscription_cant_use_a_link_made_before_nor_spend_it(
    db, subscribed, mcp, new_browser, post_with
):
    post_id = await post_with("One")
    link = await _link(mcp, post_id)
    await db.execute(update(Subscription).values(status="canceled"))
    await db.commit()

    response = await _upload(new_browser, link, png())

    assert response.status_code == 403
    assert response.json()["detail"] == "This needs a subscription. Subscribe to continue."
    await db.execute(update(Subscription).values(status="active"))
    await db.commit()
    assert (await _upload(new_browser, link, png())).status_code == 201


async def test_uploads_through_links_count_against_the_media_rate_without_spending_the_link(
    subscribed, mcp, new_browser, post_with, client
):
    post_id = await post_with("Busy.")
    link = await _link(mcp, post_id)
    for _ in range(MEDIA_PER_MINUTE):
        # A Part the Text doesn't have: refused, but counted.
        answer = await client.post(
            f"/api/v1/posts/{post_id}/text/parts/2/media",
            files={"file": ("chart.png", png(), "image/png")},
        )
        assert answer.status_code == 404

    limited = await _upload(new_browser, link, png())

    assert limited.status_code == 429
    assert await _media_of(mcp, post_id) == [[]]


async def test_a_suspended_user_cant_use_a_link_made_before(
    db, user, subscribed, fixed_clock, mcp, new_browser, post_with
):
    post_id = await post_with("One")
    link = await _link(mcp, post_id)
    await db.execute(
        update(User).values(suspended_until=datetime.now(timezone.utc) + timedelta(days=1))
    )
    await db.commit()

    response = await _upload(new_browser, link, png())

    assert response.status_code == 403
    assert response.json()["detail"] == "This upload link no longer works."


async def test_a_file_larger_than_x_takes_is_refused_and_spends_the_link(
    subscribed, mcp, new_browser, post_with
):
    post_id = await post_with("One")
    link = await _link(mcp, post_id)

    refused = await _upload(new_browser, link, padded(png(), IMAGE_MAX_BYTES + 1))

    assert refused.status_code == 422
    assert refused.json()["code"] == "MEDIA_TOO_LARGE"
    assert (await _upload(new_browser, link, png())).json()["code"] == "UPLOAD_LINK_USED"
    assert await _media_of(mcp, post_id) == [[]]


async def test_disconnecting_the_app_stops_the_links_it_made(
    subscribed, mcp, new_browser, post_with, authed_client
):
    post_id = await post_with("One")
    link = await _link(mcp, post_id)
    [connection] = (await authed_client.get(CONNECTIONS)).json()["data"]
    disconnected = await authed_client.delete(f"{CONNECTIONS}/{connection['id']}")
    assert disconnected.status_code == 204, disconnected.text

    response = await _upload(new_browser, link, png())

    assert response.status_code == 403
    assert response.json()["detail"] == "This upload link no longer works."


@pytest.mark.parametrize(
    ("after_expiry", "code"),
    [(timedelta(days=1), "UPLOAD_LINK_UNKNOWN"), (timedelta(hours=23), "UPLOAD_LINK_EXPIRED")],
)
async def test_the_publishers_pass_forgets_links_a_day_after_they_expire(
    after_expiry,
    code,
    subscribed,
    fixed_clock,
    mcp,
    new_browser,
    post_with,
    db_session_maker,
    fake_x_publisher,
    file_storage,
):
    link = await _link(mcp, await post_with("One"))
    fixed_clock.advance(timedelta(minutes=15) + after_expiry)

    await publisher.run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _upload(new_browser, link, png())).json()["code"] == code


def test_the_access_log_keeps_no_links_token(caplog):
    access_log = logging.getLogger("uvicorn.access")
    line = '%s - "%s %s HTTP/%s" %d'

    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        access_log.info(line, "1.2.3.4:5", "POST", "/api/v1/media-uploads/s3cret?x=1", "1.1", 410)
        access_log.info(line, "1.2.3.4:5", "GET", "/api/v1/posts/p1", "1.1", 200)

    assert [record.getMessage() for record in caplog.records] == [
        '1.2.3.4:5 - "POST /api/v1/media-uploads/[redacted] HTTP/1.1" 410',
        '1.2.3.4:5 - "GET /api/v1/posts/p1 HTTP/1.1" 200',
    ]
