from datetime import datetime, timedelta, timezone

from pumpkit.authors.x_reader import FetchedPost

AUTHORS = "/api/v1/inspiration-authors"
DIRECTORY = "/api/v1/author-directory"

PHOTO = "https://pbs.twimg.com/profile_images/1/levelsio_normal.jpg"
NEW_PHOTO = "https://pbs.twimg.com/profile_images/2/levelsio_normal.jpg"


def _posts(*ids: str) -> list[FetchedPost]:
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return [
        FetchedPost(post_id=post_id, text=f"post {post_id}", posted_at=start - timedelta(hours=i))
        for i, post_id in enumerate(ids)
    ]


async def test_a_user_who_is_not_subscribed_cannot_read_the_directory(client):
    response = await client.get(DIRECTORY)

    assert response.status_code == 403


async def test_adding_an_author_puts_their_x_name_and_photo_in_the_directory(
    client, subscribed, fake_x_reader
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    fake_x_reader.names["levelsio"] = "Pieter Levels"
    fake_x_reader.photos["levelsio"] = PHOTO

    added = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert (added.json()["name"], added.json()["photo_url"]) == ("Pieter Levels", PHOTO)
    assert (await client.get(DIRECTORY)).json() == {
        "data": [
            {"handle": "levelsio", "name": "Pieter Levels", "photo_url": PHOTO, "persona_count": 1}
        ]
    }


async def test_a_refresh_updates_the_entry_s_name_and_photo(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    fake_x_reader.names["levelsio"] = "Pieter Levels"
    fake_x_reader.photos["levelsio"] = PHOTO
    await client.post(AUTHORS, json={"handle": "levelsio"})
    clock.advance(timedelta(hours=2))
    fake_x_reader.names["levelsio"] = "@levelsio"
    fake_x_reader.photos["levelsio"] = NEW_PHOTO

    refreshed = await client.post(f"{AUTHORS}/levelsio/refresh")

    assert (refreshed.json()["name"], refreshed.json()["photo_url"]) == ("@levelsio", NEW_PHOTO)
    [entry] = (await client.get(DIRECTORY)).json()["data"]
    assert (entry["name"], entry["photo_url"]) == ("@levelsio", NEW_PHOTO)


async def test_a_refresh_that_finds_no_name_or_photo_keeps_the_stored_ones(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    fake_x_reader.names["levelsio"] = "Pieter Levels"
    fake_x_reader.photos["levelsio"] = PHOTO
    await client.post(AUTHORS, json={"handle": "levelsio"})
    clock.advance(timedelta(hours=2))
    fake_x_reader.names.clear()
    fake_x_reader.photos.clear()

    await client.post(f"{AUTHORS}/levelsio/refresh")

    [entry] = (await client.get(DIRECTORY)).json()["data"]
    assert (entry["name"], entry["photo_url"]) == ("Pieter Levels", PHOTO)


async def test_each_entry_counts_the_users_with_it_in_their_persona_and_names_none_of_them(
    client, subscribed, fake_x_reader, sign_in_as_another_subscribed_user
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    fake_x_reader.posts["paulg"] = _posts("2")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    await client.post(AUTHORS, json={"handle": "paulg"})
    await sign_in_as_another_subscribed_user()
    await client.post(AUTHORS, json={"handle": "levelsio"})
    await client.post(AUTHORS, json={"handle": "paulg"})
    await client.delete(f"{AUTHORS}/paulg")
    await sign_in_as_another_subscribed_user("carol@example.com")
    await client.post(AUTHORS, json={"handle": "levelsio"})

    response = await client.get(DIRECTORY)

    assert response.status_code == 200
    entries = response.json()["data"]
    assert {entry["handle"]: entry["persona_count"] for entry in entries} == {
        "levelsio": 3,
        "paulg": 1,
    }
    assert all(
        entry.keys() == {"handle", "name", "photo_url", "persona_count"} for entry in entries
    )


async def test_an_entry_stays_when_its_only_user_removes_it(client, subscribed, fake_x_reader):
    fake_x_reader.posts["levelsio"] = _posts("1")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    await client.delete(f"{AUTHORS}/levelsio")

    response = await client.get(DIRECTORY)

    assert response.json() == {
        "data": [{"handle": "levelsio", "name": None, "photo_url": None, "persona_count": 0}]
    }
