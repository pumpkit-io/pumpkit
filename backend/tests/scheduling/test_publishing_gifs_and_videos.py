"""
Publishing a GIF or a video (ADR 0021): uploaded to X in chunks with its own media category and
waited on while X processes it. A video's upload can outlast the stuck threshold and the access
token's life, so the publish keeps its claim and a fresh token through every call to X.
Post now refuses a video for now.
"""

from datetime import timedelta

from httpx import AsyncClient

from pumpkit.scheduling.publisher import run_pass
from pumpkit.scheduling.publishing import recover_stuck
from pumpkit.x_connection.x_publisher import XMediaRefusedError
from tests.media_files import animated_gif, mp4

POSTS = "/api/v1/posts"
SCHEDULED_POSTS = "/api/v1/scheduled-posts"
POST_NOW_VIDEO = "Post now can't publish a video yet. Schedule the post a minute from now instead."


async def _attach(
    client: AsyncClient, post_id: str, data: bytes, name: str, *, part: int = 1
) -> dict:
    response = await client.post(
        f"{POSTS}/{post_id}/text/parts/{part}/media", files={"file": (name, data, "")}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _due(client: AsyncClient, post_id: str, fixed_clock) -> None:
    response = await client.post(
        SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": "2026-10-10T12:05:00Z"}
    )
    assert response.status_code == 201, response.text
    fixed_clock.advance(timedelta(minutes=5))


async def _scheduled_post(client: AsyncClient, post_id: str) -> dict:
    return (await client.get(f"{POSTS}/{post_id}")).json()["scheduled_post"]


async def test_a_gif_and_a_video_go_to_x_in_their_own_categories(
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
    post_id = await post_with("A loop.", "A demo.")
    gif = await _attach(client, post_id, animated_gif(), "loop.gif")
    await client.put(
        f"{POSTS}/{post_id}/text/media/{gif['id']}/alt-text", json={"alt_text": "A cat spins."}
    )
    await _attach(client, post_id, mp4(), "demo.mp4", part=2)
    await _due(client, post_id, fixed_clock)

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"
    assert [(u.content_type, u.category, u.data) for u in fake_x_publisher.uploads] == [
        ("image/gif", "tweet_gif", animated_gif()),
        ("video/mp4", "tweet_video", mp4()),
    ]
    gif_id, video_id = (u.media_id for u in fake_x_publisher.uploads)
    assert fake_x_publisher.published_media == [[gif_id], [video_id]]
    assert [(a.media_id, a.text) for a in fake_x_publisher.alt_texts] == [(gif_id, "A cat spins.")]


def _each_upload_call_takes(fake_x_publisher, db_session_maker, fixed_clock, wait: timedelta):
    """Every call of an upload lasts `wait`, while another publisher pass recovers stuck posts."""

    async def recover() -> None:
        fixed_clock.advance(wait)
        async with db_session_maker() as session:
            await recover_stuck(session, now=fixed_clock())

    fake_x_publisher.while_calling_x_to_upload = recover


async def test_a_video_upload_outlasting_the_stuck_threshold_keeps_its_claim(
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
    post_id = await post_with("A long demo.")
    await _attach(client, post_id, mp4(total=96), "demo.mp4")
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.chunk_bytes = 32
    fake_x_publisher.processing_polls = 3
    _each_upload_call_takes(fake_x_publisher, db_session_maker, fixed_clock, timedelta(minutes=6))

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    published = await _scheduled_post(client, post_id)
    assert published["state"] == "published"
    assert published["failed_reason"] is None
    # Initialize, 3 chunks, finalize and 3 STATUS polls: 48 minutes.
    assert fake_x_publisher.upload_calls == 8
    assert fake_x_publisher.uploads[0].data == mp4(total=96)


async def test_a_token_expiring_during_a_video_upload_is_refreshed_before_the_next_call(
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
    post_id = await post_with("A very long demo.")
    await _attach(client, post_id, mp4(total=96), "demo.mp4")
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.chunk_bytes = 4
    # The token from connecting lasts two hours; 26 calls of 6 minutes take 2 h 36.
    _each_upload_call_takes(fake_x_publisher, db_session_maker, fixed_clock, timedelta(minutes=6))

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    assert (await _scheduled_post(client, post_id))["state"] == "published"
    assert fake_x_publisher.refreshes == ["refresh-1001-1"]
    sent = fake_x_publisher.upload_tokens
    assert (sent[0], sent[-1]) == ("access-1001-1", "access-1001-2")
    assert fake_x_publisher.published[0][0] == "access-1001-2"


async def test_a_video_x_fails_to_process_fails_the_post_with_xs_reason(
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
    post_id = await post_with("A broken demo.")
    await _attach(client, post_id, mp4(), "demo.mp4")
    await _due(client, post_id, fixed_clock)
    fake_x_publisher.fail_upload = XMediaRefusedError(None, "Unsupported video codec.")

    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)

    failed = await _scheduled_post(client, post_id)
    assert failed["state"] == "failed"
    assert failed["failed_reason"] == ("X refused the post's media: Unsupported video codec.")
    assert fake_x_publisher.published == []


async def test_post_now_refuses_a_video_for_now(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Right now.", "With a demo.")
    await _attach(client, post_id, mp4(), "demo.mp4", part=2)

    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})

    assert response.status_code == 422, response.text
    assert response.json() == {"detail": POST_NOW_VIDEO, "code": "POST_NOW_VIDEO"}
    assert await _scheduled_post(client, post_id) is None
    assert fake_x_publisher.uploads == []


async def test_post_now_of_a_scheduled_post_with_a_video_is_refused_and_it_stays_scheduled(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("Later, with a demo.")
    await _attach(client, post_id, mp4(), "demo.mp4")
    scheduled = await client.post(
        SCHEDULED_POSTS, json={"post_id": post_id, "publish_at": "2026-10-10T14:00:00Z"}
    )

    response = await client.patch(
        f"{SCHEDULED_POSTS}/{scheduled.json()['id']}", json={"publish_now": True}
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "POST_NOW_VIDEO"
    assert (await _scheduled_post(client, post_id))["state"] == "scheduled"
    assert fake_x_publisher.uploads == []


async def test_post_now_with_a_gif_publishes_within_the_request(
    client, subscribed, fake_x_publisher, fixed_clock, connect_x, post_with
):
    await connect_x()
    post_id = await post_with("A loop, now.")
    await _attach(client, post_id, animated_gif(), "loop.gif")

    response = await client.post(SCHEDULED_POSTS, json={"post_id": post_id, "publish_now": True})

    assert response.json()["state"] == "published", response.text
    assert [u.category for u in fake_x_publisher.uploads] == ["tweet_gif"]
