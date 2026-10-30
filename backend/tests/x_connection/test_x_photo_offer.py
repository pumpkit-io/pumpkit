from typing import Optional
from urllib.parse import parse_qs, urlsplit

from httpx import AsyncClient

from pumpkit.auth.models import User
from pumpkit.x_connection.x_publisher import XAccount

X_CONNECTION = "/api/v1/x-connection"
USE_PHOTO = f"{X_CONNECTION}/photo/use"
DECLINE_PHOTO = f"{X_CONNECTION}/photo/decline"
PROFILE = "/api/v1/users/me"

X_PHOTO = "https://pbs.twimg.com/profile_images/1/ada_200x200.jpg"
X_PHOTO_DATA_URL = "data:image/jpeg;base64,eA=="
UPLOADED_PHOTO = "data:image/png;base64,dXBsb2FkZWQ="


async def _connect(client: AsyncClient):
    started = await client.post(f"{X_CONNECTION}/authorizations")
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
    completed = await client.post(
        f"{X_CONNECTION}/authorizations/complete", json={"code": "the-code", "state": state}
    )
    assert completed.status_code == 200, completed.text
    return completed


def _x_account_with_photo(fake_x_publisher, photo_url: Optional[str] = X_PHOTO) -> None:
    fake_x_publisher.account = XAccount(
        user_id="1001", handle="ada", subscription_type="None", photo_url=photo_url
    )


async def test_a_user_with_no_photo_is_offered_the_x_photo(
    client, subscribed, fake_x_publisher, clock
):
    _x_account_with_photo(fake_x_publisher)

    completed = await _connect(client)

    assert completed.json()["offer_photo"] is True
    assert (await client.get(X_CONNECTION)).json()["offer_photo"] is True


async def test_a_user_with_a_photo_is_not_offered_the_x_photo(
    client, subscribed, fake_x_publisher, clock
):
    await client.patch(PROFILE, json={"avatar_data_url": UPLOADED_PHOTO})
    _x_account_with_photo(fake_x_publisher)

    completed = await _connect(client)

    assert completed.json()["offer_photo"] is False


async def test_a_user_who_removed_their_photo_is_not_offered_the_x_photo(
    client, subscribed, fake_x_publisher, clock
):
    await client.patch(PROFILE, json={"avatar_data_url": None})
    _x_account_with_photo(fake_x_publisher)

    completed = await _connect(client)

    assert completed.json()["offer_photo"] is False


async def test_an_x_account_without_a_photo_offers_nothing(
    client, subscribed, fake_x_publisher, clock
):
    _x_account_with_photo(fake_x_publisher, photo_url=None)

    completed = await _connect(client)

    assert completed.json()["offer_photo"] is False


async def test_using_the_x_photo_makes_it_the_user_s_photo_and_ends_the_offer(
    client, subscribed, fake_x_publisher, fake_photo_fetcher, clock
):
    _x_account_with_photo(fake_x_publisher)
    fake_photo_fetcher.photos[X_PHOTO] = X_PHOTO_DATA_URL
    await _connect(client)

    used = await client.post(USE_PHOTO)

    assert used.status_code == 200, used.text
    assert used.json()["avatar_data_url"] == X_PHOTO_DATA_URL
    assert (await client.get(PROFILE)).json()["avatar_data_url"] == X_PHOTO_DATA_URL
    assert (await client.get(X_CONNECTION)).json()["offer_photo"] is False


async def test_using_the_x_photo_marks_the_photo_chosen(
    client, db_session_maker, user, subscribed, fake_x_publisher, fake_photo_fetcher, clock
):
    _x_account_with_photo(fake_x_publisher)
    fake_photo_fetcher.photos[X_PHOTO] = X_PHOTO_DATA_URL
    await _connect(client)

    await client.post(USE_PHOTO)

    # Read from the database: with a Photo in place, the marker changes nothing a response shows.
    async with db_session_maker() as db:
        stored = await db.get_one(User, user.id)
    assert stored.photo_chosen_at is not None


async def test_not_now_ends_the_offer_for_this_connection(
    client, subscribed, fake_x_publisher, clock
):
    _x_account_with_photo(fake_x_publisher)
    await _connect(client)

    declined = await client.post(DECLINE_PHOTO)

    assert declined.status_code == 204
    assert (await client.get(X_CONNECTION)).json()["offer_photo"] is False
    assert (await client.get(PROFILE)).json()["avatar_data_url"] is None


async def test_reconnecting_after_disconnecting_offers_the_x_photo_again(
    client, subscribed, fake_x_publisher, clock
):
    _x_account_with_photo(fake_x_publisher)
    await _connect(client)
    await client.post(DECLINE_PHOTO)
    await client.delete(X_CONNECTION)

    reconnected = await _connect(client)

    assert reconnected.json()["offer_photo"] is True


async def test_reconnecting_without_disconnecting_offers_the_x_photo_again(
    client, subscribed, fake_x_publisher, clock
):
    _x_account_with_photo(fake_x_publisher)
    await _connect(client)
    await client.post(DECLINE_PHOTO)

    reconnected = await _connect(client)

    assert reconnected.json()["offer_photo"] is True


async def test_a_failed_copy_answers_with_an_error_and_changes_nothing(
    client, subscribed, fake_x_publisher, clock
):
    _x_account_with_photo(fake_x_publisher)
    await _connect(client)

    used = await client.post(USE_PHOTO)

    assert used.status_code == 502
    assert used.json()["detail"] == "Couldn't use your X photo. Try again."
    assert (await client.get(PROFILE)).json()["avatar_data_url"] is None
    assert (await client.get(X_CONNECTION)).json()["offer_photo"] is True


async def test_a_user_with_a_photo_can_switch_to_the_x_photo(
    client, subscribed, fake_x_publisher, fake_photo_fetcher, clock
):
    await client.patch(PROFILE, json={"avatar_data_url": UPLOADED_PHOTO})
    _x_account_with_photo(fake_x_publisher)
    fake_photo_fetcher.photos[X_PHOTO] = X_PHOTO_DATA_URL
    await _connect(client)

    used = await client.post(USE_PHOTO)

    assert used.status_code == 200
    assert (await client.get(PROFILE)).json()["avatar_data_url"] == X_PHOTO_DATA_URL


async def test_disconnecting_keeps_the_photo_taken_from_x(
    client, subscribed, fake_x_publisher, fake_photo_fetcher, clock
):
    _x_account_with_photo(fake_x_publisher)
    fake_photo_fetcher.photos[X_PHOTO] = X_PHOTO_DATA_URL
    await _connect(client)
    await client.post(USE_PHOTO)

    await client.delete(X_CONNECTION)

    assert (await client.get(PROFILE)).json()["avatar_data_url"] == X_PHOTO_DATA_URL


async def test_an_x_account_without_a_photo_has_none_to_use(
    client, subscribed, fake_x_publisher, fake_photo_fetcher, clock
):
    _x_account_with_photo(fake_x_publisher, photo_url=None)
    await _connect(client)

    used = await client.post(USE_PHOTO)

    assert used.status_code == 404
    assert fake_photo_fetcher.fetched == []


async def test_without_an_x_connection_there_is_no_photo_to_use_or_decline(client):
    assert (await client.post(USE_PHOTO)).status_code == 404
    assert (await client.post(DECLINE_PHOTO)).status_code == 404
