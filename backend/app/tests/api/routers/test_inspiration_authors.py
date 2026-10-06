from datetime import datetime, timedelta, timezone

from app.core.x_reader import FetchedPost

AUTHORS = "/api/v1/inspiration-authors"


def _posts(*ids: str) -> list[FetchedPost]:
    """Original posts with these ids, the first newest."""
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return [
        FetchedPost(post_id=post_id, text=f"post {post_id}", posted_at=start - timedelta(hours=i))
        for i, post_id in enumerate(ids)
    ]


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
            {"handle": "levelsio", "last_fetched_at": fetched_at, "post_count": 2},
            {"handle": "paulg", "last_fetched_at": fetched_at, "post_count": 1},
        ]
    }


async def test_a_user_who_is_not_subscribed_may_list_authors(client):
    response = await client.get(AUTHORS)

    assert response.status_code == 200
    assert response.json() == {"data": []}


async def test_adding_a_handle_x_does_not_know_returns_404(client, subscribed):
    response = await client.post(AUTHORS, json={"handle": "nobody_here"})

    assert response.status_code == 404
    assert response.json()["detail"] == "@nobody_here doesn't exist on X."
    assert (await client.get(AUTHORS)).json() == {"data": []}


async def test_adding_a_handle_with_no_original_posts_returns_422(
    client, subscribed, fake_x_reader
):
    fake_x_reader.posts["replyguy"] = []

    response = await client.post(AUTHORS, json={"handle": "replyguy"})

    assert response.status_code == 422
    assert response.json()["detail"] == "@replyguy has no original posts to learn from."
    assert (await client.get(AUTHORS)).json() == {"data": []}


async def test_adding_a_handle_already_listed_in_another_case_returns_409_without_fetching(
    client, subscribed, fake_x_reader
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    await client.post(AUTHORS, json={"handle": "levelsio"})

    response = await client.post(AUTHORS, json={"handle": "@LevelsIO"})

    assert response.status_code == 409
    assert response.json()["detail"] == "@levelsio is already one of your Inspiration authors."
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
    assert response.json()["detail"] == "This needs a Subscription. Subscribe to continue."
    assert fake_x_reader.calls == []


async def test_a_user_whose_subscription_ended_gets_403_when_removing(
    client, db, subscribed, fake_x_reader
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    subscribed.status = "canceled"
    await db.commit()

    response = await client.delete(f"{AUTHORS}/levelsio")

    assert response.status_code == 403
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
    client, subscribed, fake_x_reader
):
    fake_x_reader.posts["levelsio"] = _posts("1", "2")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    await client.delete(f"{AUTHORS}/levelsio")
    fake_x_reader.posts["levelsio"] = _posts("3", "1", "2")

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert response.status_code == 201
    assert response.json()["post_count"] == 3


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
