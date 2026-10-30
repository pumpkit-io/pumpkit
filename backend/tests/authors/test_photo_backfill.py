from datetime import datetime, timedelta, timezone

from pumpkit.authors.photo_backfill import BackfillResult, backfill_author_photos
from pumpkit.authors.x_reader import FetchedPost

AUTHORS = "/api/v1/inspiration-authors"
LEVELSIO_PHOTO = "https://pbs.twimg.com/profile_images/1/levelsio_normal.jpg"
PAULG_PHOTO = "https://pbs.twimg.com/profile_images/2/paulg_normal.jpg"


def _posts(post_id: str) -> list[FetchedPost]:
    return [
        FetchedPost(
            post_id=post_id,
            text=f"post {post_id}",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]


async def _add_authors_listed_before_photos(client, fake_x_reader, *handles: str) -> None:
    for i, handle in enumerate(handles):
        fake_x_reader.posts[handle] = _posts(str(i))
        await client.post(AUTHORS, json={"handle": handle})
    fake_x_reader.calls.clear()


async def test_the_backfill_stores_the_photo_of_each_listed_author_without_one(
    client, db_session_maker, subscribed, fake_x_reader, clock
):
    await _add_authors_listed_before_photos(client, fake_x_reader, "levelsio", "paulg")
    before = (await client.get(AUTHORS)).json()["data"]
    fake_x_reader.photos.update(levelsio=LEVELSIO_PHOTO, paulg=PAULG_PHOTO)

    result = await backfill_author_photos(db_session_maker, fake_x_reader)

    assert result == BackfillResult(filled=2, skipped=0)
    assert sorted(fake_x_reader.calls) == ["levelsio", "paulg"]
    after = (await client.get(AUTHORS)).json()["data"]
    assert [author["photo_url"] for author in after] == [LEVELSIO_PHOTO, PAULG_PHOTO]
    assert [a["last_fetched_at"] for a in after] == [a["last_fetched_at"] for a in before]


async def test_the_backfill_leaves_the_refresh_cooldown_where_it_was(
    client, db_session_maker, subscribed, fake_x_reader, clock
):
    await _add_authors_listed_before_photos(client, fake_x_reader, "levelsio")
    clock.advance(timedelta(hours=2))
    fake_x_reader.photos["levelsio"] = LEVELSIO_PHOTO
    await backfill_author_photos(db_session_maker, fake_x_reader)

    response = await client.post(f"{AUTHORS}/levelsio/refresh")

    assert response.status_code == 200


async def test_a_handle_that_fails_is_skipped_and_the_rest_are_filled(
    client, db_session_maker, subscribed, fake_x_reader
):
    await _add_authors_listed_before_photos(client, fake_x_reader, "levelsio", "paulg")
    del fake_x_reader.posts["levelsio"]
    fake_x_reader.photos["paulg"] = PAULG_PHOTO

    result = await backfill_author_photos(db_session_maker, fake_x_reader)

    assert result == BackfillResult(filled=1, skipped=1)
    after = (await client.get(AUTHORS)).json()["data"]
    assert [author["photo_url"] for author in after] == [None, PAULG_PHOTO]


async def test_a_second_run_reads_nothing_from_x(
    client, db_session_maker, subscribed, fake_x_reader
):
    await _add_authors_listed_before_photos(client, fake_x_reader, "levelsio", "paulg")
    fake_x_reader.photos.update(levelsio=LEVELSIO_PHOTO, paulg=PAULG_PHOTO)
    await backfill_author_photos(db_session_maker, fake_x_reader)
    fake_x_reader.calls.clear()

    result = await backfill_author_photos(db_session_maker, fake_x_reader)

    assert result == BackfillResult(filled=0, skipped=0)
    assert fake_x_reader.calls == []
