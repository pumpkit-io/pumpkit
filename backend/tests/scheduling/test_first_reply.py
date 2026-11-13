"""
A single post with a first reply goes out as two Parts, the first reply as a reply to the post,
through Thread publishing (ADR 0014, 0027). Each counts as an X post, and as a link post when it
holds a link. Nothing with the `[link]` placeholder is scheduled or posted.
"""

from datetime import timedelta

import pytest

from pumpkit.scheduling.publisher import run_pass
from pumpkit.x_connection.x_publisher import XPostRejectedError
from tests.mcp_client import error_text
from tests.media_files import png
from tests.scheduling.reading import scheduled_posts

POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
USAGE = "/api/v1/usage"
LATER = "2026-10-10T14:00:00Z"
PLACEHOLDER = "Replace [link] with the real link first."


@pytest.fixture
async def connected(subscribed, fixed_clock, connect_x) -> None:
    await connect_x()


def _texts(scheduled_post: dict) -> list[str]:
    return [part["text"] for part in scheduled_post["parts"]]


async def test_post_now_sends_the_first_reply_as_a_reply_to_the_post(
    client, connected, post_with, fake_x_publisher
):
    post_id = await post_with("The post.", "Try it: pumpkit.io/calc", first_reply=True)

    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})

    assert response.status_code == 201, response.text
    published = response.json()
    assert published["state"] == "published"
    assert published["first_reply"] is True
    assert _texts(published) == ["The post.", "Try it: pumpkit.io/calc"]
    assert [text for _, text in fake_x_publisher.published] == [
        "The post.",
        "Try it: pumpkit.io/calc",
    ]
    assert fake_x_publisher.replied_to == [None, "1890000000000000001"]


async def test_a_scheduled_first_reply_is_published_once_by_the_publisher(
    client,
    connected,
    post_with,
    fake_x_publisher,
    fixed_clock,
    db_session_maker,
    file_storage,
):
    post_id = await post_with("The post.", "More: pumpkit.io/calc", first_reply=True)
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})
    assert scheduled.status_code == 201, scheduled.text
    fixed_clock.advance(timedelta(hours=3))

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert [text for _, text in fake_x_publisher.published] == [
        "The post.",
        "More: pumpkit.io/calc",
    ]
    assert fake_x_publisher.replied_to == [None, "1890000000000000001"]
    [listed] = await scheduled_posts(client)
    assert listed["state"] == "published"


async def test_a_first_reply_x_refuses_fails_the_post_and_names_the_first_reply(
    client, connected, post_with, fake_x_publisher
):
    post_id = await post_with("The post.", "Try it: pumpkit.io/calc", first_reply=True)
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = 2

    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})

    failed = response.json()
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == "X refused the first reply: Nope"
    assert [part["live"] for part in failed["parts"]] == [True, False]

    fake_x_publisher.fail_publish = None
    fake_x_publisher.fail_publish_on = None
    retried = await client.patch(
        f"{SCHEDULED_POSTS}/{failed['id']}", json={"copy_text": True, "publish_now": True}
    )

    # Rescheduling publishes only the first reply, under the post already on X.
    assert retried.json()["state"] == "published", retried.text
    assert [text for _, text in fake_x_publisher.published[2:]] == ["Try it: pumpkit.io/calc"]
    assert fake_x_publisher.replied_to[2:] == ["1890000000000000001"]


async def test_a_first_reply_counts_as_an_x_post_and_as_a_link_post_with_a_link(
    client, connected, post_with
):
    post_id = await post_with("The post.", "Try it: pumpkit.io/calc", first_reply=True)

    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})

    assert scheduled.status_code == 201, scheduled.text
    allowance = (await client.get(USAGE)).json()["allowance"]
    assert allowance["x_posts"]["used"] == 2
    assert allowance["link_x_posts"]["used"] == 1


async def test_the_posts_list_reads_a_scheduled_first_reply_as_a_single_post(
    client, connected, post_with
):
    post_id = await post_with("The post.", "Try it: pumpkit.io/calc", first_reply=True)
    draft = (await client.get(POSTS)).json()["data"][0]
    assert (draft["format"], draft["first_reply"]) == ("post", True)

    await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})

    [row] = (await client.get(POSTS, params={"status": "scheduled"})).json()["data"]
    assert (row["format"], row["first_reply"]) == ("post", True)
    assert row["parts"] == ["The post.", "Try it: pumpkit.io/calc"]


@pytest.mark.parametrize(
    "parts",
    [
        ("The post.", "Try it: [link]"),
        ("Sign up at [link] today.", "More soon."),
        ("The post.", "Try it: [LINK]"),
        ("The post.", "Try it: [ Link ]"),
    ],
)
@pytest.mark.parametrize("when", [{"publish_at": LATER}, {"publish_now": True}])
async def test_scheduling_or_posting_a_text_with_the_link_placeholder_is_refused(
    client, connected, post_with, fake_x_publisher, parts, when
):
    post_id = await post_with(*parts, first_reply=True)

    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, **when})

    assert response.status_code == 422
    assert response.json()["detail"] == PLACEHOLDER
    assert fake_x_publisher.published == []
    assert await scheduled_posts(client) == []


async def test_a_thread_with_the_link_placeholder_is_refused_too(client, connected, post_with):
    post_id = await post_with("One.", "Two, at [link].")

    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})

    assert response.status_code == 422
    assert response.json()["detail"] == PLACEHOLDER


async def test_editing_a_scheduled_post_to_hold_the_link_placeholder_is_refused(
    client, connected, post_with
):
    post_id = await post_with("The post.", "Try it: pumpkit.io/calc", first_reply=True)
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled.json()['id']}",
        json={"parts": ["The post.", "Try it: [link]"]},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == PLACEHOLDER
    [kept] = await scheduled_posts(client)
    assert _texts(kept) == ["The post.", "Try it: pumpkit.io/calc"]
    assert kept["first_reply"] is True


async def test_editing_a_scheduled_first_reply_keeps_it_a_first_reply(client, connected, post_with):
    post_id = await post_with("The post.", "Try it: pumpkit.io/calc", first_reply=True)
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})

    edited = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled.json()['id']}",
        json={"parts": ["The post.", "Get it: pumpkit.io/calc"]},
    )

    assert edited.status_code == 200, edited.text
    assert edited.json()["first_reply"] is True


@pytest.mark.parametrize("tool", ["schedule_post", "post_now"])
async def test_an_ai_app_is_refused_the_link_placeholder_too(
    client, connected, mcp, post_with, fake_x_publisher, tool
):
    post_id = await post_with("The post.", "Try it: [link]", first_reply=True)
    arguments = {"publish_at": LATER} if tool == "schedule_post" else {}

    result = await mcp.call_tool(tool, post_id=post_id, **arguments)

    assert result["isError"] is True
    assert error_text(result) == PLACEHOLDER
    assert fake_x_publisher.published == []


async def test_media_goes_on_the_post_not_on_its_first_reply(client, connected, post_with):
    post_id = await post_with("The post.", "Try it: pumpkit.io/calc", first_reply=True)

    refused = await client.post(
        f"{POSTS}/{post_id}/text/parts/2/media",
        files={"file": ("photo.png", png(), "image/png")},
    )

    assert refused.status_code == 409
    assert (
        refused.json()["detail"] == "A first reply goes out without media. Attach it to the post."
    )


async def test_an_ai_app_reads_the_first_reply_and_is_told_about_it(
    client, connected, mcp, post_with
):
    post_id = await post_with("The post.", "Try it: pumpkit.io/calc", first_reply=True)

    instructions = (await mcp.initialize())["instructions"]
    read = (await mcp.call_tool("get_post", post_id=post_id))["structuredContent"]

    assert "first reply" in instructions
    assert "`[link]`" in instructions
    assert "each first reply counting as one" in instructions
    assert (read["text"]["format"], read["text"]["first_reply"]) == ("post", True)
    assert read["versions"][0]["first_reply"] is True


async def test_restoring_a_first_reply_over_a_part_already_on_x_with_media_is_refused(
    client, connected, post_with, next_version, fake_x_publisher
):
    post_id = await post_with("The post.", "Try it: pumpkit.io/calc", first_reply=True)
    await next_version(post_id, "One.", "Two.")
    attached = await client.post(
        f"{POSTS}/{post_id}/text/parts/2/media",
        files={"file": ("photo.png", png(), "image/png")},
    )
    assert attached.status_code == 201, attached.text
    fake_x_publisher.fail_publish = XPostRejectedError(400, "Nope")
    fake_x_publisher.fail_publish_on = 2
    failed = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})
    assert failed.json()["state"] == "failed", failed.text

    restored = await client.post(f"{POSTS}/{post_id}/versions/1/restore")

    assert restored.status_code == 409, restored.text
    assert restored.json()["detail"] == (
        "The post is already on X, so it can't take the media of the parts this version drops."
    )
    text = (await client.get(f"{POSTS}/{post_id}")).json()["text"]
    assert [[m["id"] for m in part["media"]] for part in text["parts"]] == [
        [],
        [attached.json()["id"]],
    ]


async def test_a_blank_first_reply_is_named_as_the_first_reply(client, connected, post_with):
    post_id = await post_with("The post.", "Try it: pumpkit.io/calc", first_reply=True)
    scheduled = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": LATER})

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled.json()['id']}", json={"parts": ["The post.", "  "]}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Write the first reply first."
