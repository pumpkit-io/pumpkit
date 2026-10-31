from datetime import datetime, timedelta, timezone

from pumpkit.authors.x_reader import FetchedPost

AUTHORS = "/api/v1/inspiration-authors"


def _posts(*ids: str) -> list[FetchedPost]:
    """Original posts with these ids, the first newest."""
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return [
        FetchedPost(post_id=post_id, text=f"post {post_id}", posted_at=start - timedelta(hours=i))
        for i, post_id in enumerate(ids)
    ]


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def test_a_subscribed_user_adds_a_handle_and_its_posts_are_fetched_at_once(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["levelsio"] = _posts("1", "2")

    response = await client.post(AUTHORS, json={"handle": "@LevelsIO"})

    assert response.status_code == 201
    assert response.json() == {
        "handle": "levelsio",
        "last_fetched_at": clock().isoformat().replace("+00:00", "Z"),
        "post_count": 2,
        "name": None,
        "photo_url": None,
    }
    assert fake_x_reader.calls == ["levelsio"]


async def test_the_list_shows_authors_in_the_order_they_were_added(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["levelsio"] = _posts("1", "2")
    fake_x_reader.posts["paulg"] = _posts("3")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    await client.post(AUTHORS, json={"handle": "paulg"})

    response = await client.get(AUTHORS)

    assert response.status_code == 200
    fetched_at = clock().isoformat().replace("+00:00", "Z")
    assert response.json() == {
        "data": [
            {
                "handle": "levelsio",
                "last_fetched_at": fetched_at,
                "post_count": 2,
                "name": None,
                "photo_url": None,
            },
            {
                "handle": "paulg",
                "last_fetched_at": fetched_at,
                "post_count": 1,
                "name": None,
                "photo_url": None,
            },
        ]
    }


async def test_adding_a_handle_x_does_not_know_returns_404(client, subscribed):
    response = await client.post(AUTHORS, json={"handle": "nobody_here"})

    assert response.status_code == 404
    assert response.json()["detail"] == "@nobody_here isn't on X"
    assert (await client.get(AUTHORS)).json() == {"data": []}


async def test_adding_a_handle_with_no_original_posts_returns_422(
    client, subscribed, fake_x_reader
):
    fake_x_reader.posts["replyguy"] = []

    response = await client.post(AUTHORS, json={"handle": "replyguy"})

    assert response.status_code == 422
    assert response.json()["detail"] == "@replyguy has no posts of its own to learn from"
    assert (await client.get(AUTHORS)).json() == {"data": []}


async def test_adding_a_handle_already_listed_in_another_case_returns_409_without_fetching(
    client, subscribed, fake_x_reader
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    await client.post(AUTHORS, json={"handle": "levelsio"})

    response = await client.post(AUTHORS, json={"handle": "@LevelsIO"})

    assert response.status_code == 409
    assert response.json()["detail"] == "@levelsio is already one of your inspiration authors."
    assert fake_x_reader.calls == ["levelsio"]


async def test_adding_a_fourth_author_returns_409_without_fetching(
    client, subscribed, fake_x_reader
):
    for handle in ["a", "b", "c", "d"]:
        fake_x_reader.posts[handle] = _posts(f"{handle}1")
    for handle in ["a", "b", "c"]:
        assert (await client.post(AUTHORS, json={"handle": handle})).status_code == 201

    response = await client.post(AUTHORS, json={"handle": "d"})

    assert response.status_code == 409
    assert "up to 3 Inspiration authors" in response.json()["detail"]
    assert fake_x_reader.calls == ["a", "b", "c"]
    assert [a["handle"] for a in (await client.get(AUTHORS)).json()["data"]] == ["a", "b", "c"]


async def test_a_handle_that_is_not_an_x_handle_returns_422_without_fetching(
    client, subscribed, fake_x_reader
):
    response = await client.post(AUTHORS, json={"handle": "two words"})

    assert response.status_code == 422
    assert fake_x_reader.calls == []


async def test_a_user_who_is_not_subscribed_gets_403_when_adding(client, fake_x_reader):
    fake_x_reader.posts["levelsio"] = _posts("1")

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert response.status_code == 403
    assert response.json()["detail"] == "This needs a subscription. Subscribe to continue."
    assert fake_x_reader.calls == []


async def test_a_user_without_a_subscription_adds_and_removes_where_no_plans_are_sold(
    client, sells_no_plans, fake_x_reader
):
    fake_x_reader.posts["levelsio"] = _posts("1")

    added = await client.post(AUTHORS, json={"handle": "levelsio"})
    removed = await client.delete(f"{AUTHORS}/levelsio")

    assert added.status_code == 201
    assert removed.status_code == 204


async def test_a_user_whose_subscription_ended_gets_403_when_removing(
    client, db, subscribed, fake_x_reader
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    subscribed.status = "canceled"
    await db.commit()

    response = await client.delete(f"{AUTHORS}/levelsio")

    assert response.status_code == 403
    subscribed.status = "active"
    await db.commit()
    assert [a["handle"] for a in (await client.get(AUTHORS)).json()["data"]] == ["levelsio"]


async def test_removing_an_author_takes_it_off_the_list_and_keeps_its_posts(
    client, subscribed, fake_x_reader
):
    fake_x_reader.posts["levelsio"] = _posts("1", "2")
    fake_x_reader.posts["paulg"] = _posts("3")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    await client.post(AUTHORS, json={"handle": "paulg"})

    response = await client.delete(f"{AUTHORS}/LevelsIO")

    assert response.status_code == 204
    assert [a["handle"] for a in (await client.get(AUTHORS)).json()["data"]] == ["paulg"]
    # Re-added with a fetch that returns only one post, it still counts both stored ones.
    fake_x_reader.posts["levelsio"] = _posts("1")
    readded = await client.post(AUTHORS, json={"handle": "levelsio"})
    assert readded.json()["post_count"] == 2


async def test_removing_a_handle_not_on_the_list_returns_404(client, subscribed):
    response = await client.delete(f"{AUTHORS}/levelsio")

    assert response.status_code == 404


async def test_a_refetch_stores_only_the_posts_not_already_stored(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["levelsio"] = _posts("1", "2")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    await client.delete(f"{AUTHORS}/levelsio")
    clock.advance(timedelta(days=7))
    fake_x_reader.posts["levelsio"] = _posts("3", "1", "2")

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert response.status_code == 201
    assert response.json()["post_count"] == 3


async def test_adding_a_handle_fetched_a_week_ago_fetches_it_again(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["levelsio"] = _posts("1", "2")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    await client.delete(f"{AUTHORS}/levelsio")
    clock.advance(timedelta(days=7))
    fake_x_reader.posts["levelsio"] = _posts("3", "1", "2")

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert response.status_code == 201
    assert response.json() == {
        "handle": "levelsio",
        "last_fetched_at": _iso(clock()),
        "post_count": 3,
        "name": None,
        "photo_url": None,
    }
    assert fake_x_reader.calls == ["levelsio", "levelsio"]


async def test_adding_an_author_without_the_twitterapi_io_key_fails_clearly(
    client, subscribed, fake_x_reader
):
    fake_x_reader.not_configured = True

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert response.status_code == 503
    assert "TWITTERAPI_IO_API_KEY" in response.json()["detail"]


async def test_a_twitterapi_io_failure_returns_502_and_stores_nothing(
    client, subscribed, fake_x_reader, assert_reported_502
):
    fake_x_reader.fail = True

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert_reported_502(response)
    assert (await client.get(AUTHORS)).json() == {"data": []}


async def test_refreshing_an_author_stores_its_new_posts_and_updates_its_fetch_time(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["levelsio"] = _posts("1", "2")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    clock.advance(timedelta(hours=2))
    fake_x_reader.posts["levelsio"] = _posts("3", "1", "2")

    response = await client.post(f"{AUTHORS}/LevelsIO/refresh")

    assert response.status_code == 200
    expected = {
        "handle": "levelsio",
        "last_fetched_at": _iso(clock()),
        "post_count": 3,
        "name": None,
        "photo_url": None,
    }
    assert response.json() == expected
    assert (await client.get(AUTHORS)).json() == {"data": [expected]}
    assert fake_x_reader.calls == ["levelsio", "levelsio"]


PHOTO = "https://pbs.twimg.com/profile_images/1/levelsio_normal.jpg"
NEW_PHOTO = "https://pbs.twimg.com/profile_images/2/levelsio_normal.jpg"


async def test_adding_an_author_stores_their_x_photo_for_every_user_who_lists_them(
    client, subscribed, fake_x_reader, sign_in_as_another_subscribed_user
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    fake_x_reader.photos["levelsio"] = PHOTO

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert response.json()["photo_url"] == PHOTO
    await sign_in_as_another_subscribed_user()
    added_without_a_fetch = await client.post(AUTHORS, json={"handle": "levelsio"})
    assert added_without_a_fetch.json()["photo_url"] == PHOTO
    assert (await client.get(AUTHORS)).json()["data"][0]["photo_url"] == PHOTO
    assert fake_x_reader.calls == ["levelsio"]


async def test_a_refetch_replaces_the_stored_photo(client, subscribed, fake_x_reader, clock):
    fake_x_reader.posts["levelsio"] = _posts("1")
    fake_x_reader.photos["levelsio"] = PHOTO
    await client.post(AUTHORS, json={"handle": "levelsio"})
    clock.advance(timedelta(hours=2))
    fake_x_reader.photos["levelsio"] = NEW_PHOTO

    response = await client.post(f"{AUTHORS}/levelsio/refresh")

    assert response.json()["photo_url"] == NEW_PHOTO
    assert (await client.get(AUTHORS)).json()["data"][0]["photo_url"] == NEW_PHOTO


async def test_a_refetch_that_finds_no_photo_keeps_the_stored_one(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    fake_x_reader.photos["levelsio"] = PHOTO
    await client.post(AUTHORS, json={"handle": "levelsio"})
    clock.advance(timedelta(hours=2))
    del fake_x_reader.photos["levelsio"]

    response = await client.post(f"{AUTHORS}/levelsio/refresh")

    assert response.json()["photo_url"] == PHOTO


async def test_refreshing_a_handle_fetched_less_than_an_hour_ago_returns_429_with_when_to_retry(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    fetched_at = clock()
    clock.advance(timedelta(minutes=45))

    response = await client.post(f"{AUTHORS}/levelsio/refresh")

    assert response.status_code == 429
    assert response.json() == {
        "detail": "@levelsio was fetched less than an hour ago.",
        "retry_at": _iso(fetched_at + timedelta(hours=1)),
    }
    assert response.headers["Retry-After"] == str(15 * 60)
    assert fake_x_reader.calls == ["levelsio"]


async def test_the_cooldown_is_per_handle_so_another_users_fetch_holds_it(
    client, subscribed, fake_x_reader, clock, sign_in_as_another_subscribed_user
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    clock.advance(timedelta(minutes=90))
    await client.post(f"{AUTHORS}/levelsio/refresh")
    await sign_in_as_another_subscribed_user()
    await client.post(AUTHORS, json={"handle": "levelsio"})
    clock.advance(timedelta(minutes=59, seconds=59))

    response = await client.post(f"{AUTHORS}/levelsio/refresh")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    assert fake_x_reader.calls == ["levelsio", "levelsio"]


async def test_a_handle_can_be_refreshed_again_exactly_an_hour_after_its_last_fetch(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    clock.advance(timedelta(hours=1))

    response = await client.post(f"{AUTHORS}/levelsio/refresh")

    assert response.status_code == 200
    assert response.json()["last_fetched_at"] == _iso(clock())


async def test_refreshing_a_handle_not_on_the_list_returns_404_without_fetching(
    client, subscribed, fake_x_reader
):
    fake_x_reader.posts["levelsio"] = _posts("1")

    response = await client.post(f"{AUTHORS}/levelsio/refresh")

    assert response.status_code == 404
    assert fake_x_reader.calls == []


async def test_a_user_whose_subscription_ended_gets_403_when_refreshing(
    client, db, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    subscribed.status = "canceled"
    await db.commit()
    clock.advance(timedelta(hours=2))

    response = await client.post(f"{AUTHORS}/levelsio/refresh")

    assert response.status_code == 403
    assert fake_x_reader.calls == ["levelsio"]


async def test_refreshing_without_the_twitterapi_io_key_fails_clearly(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    clock.advance(timedelta(hours=2))
    fake_x_reader.not_configured = True

    response = await client.post(f"{AUTHORS}/levelsio/refresh")

    assert response.status_code == 503
    assert "TWITTERAPI_IO_API_KEY" in response.json()["detail"]


async def test_refreshing_a_handle_x_no_longer_knows_returns_404(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    clock.advance(timedelta(hours=2))
    del fake_x_reader.posts["levelsio"]

    response = await client.post(f"{AUTHORS}/levelsio/refresh")

    assert response.status_code == 404
    assert response.json()["detail"] == "@levelsio isn't on X"
