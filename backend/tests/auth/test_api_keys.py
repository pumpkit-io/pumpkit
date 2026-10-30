"""API key management through the `/api-keys` routes, authenticated by the browser Session."""

import hashlib
import re
from datetime import timedelta

from sqlalchemy import select

from pumpkit.auth.models import ApiKey, User
from tests.conftest import FIXED_NOW

API_KEYS = "/api/v1/api-keys"


def _iso(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


async def test_creating_a_key_returns_the_secret_and_the_claude_command_once(
    client, subscribed, fixed_clock
):
    response = await client.post(API_KEYS, json={"name": "Work laptop"})

    assert response.status_code == 201
    body = response.json()
    secret = body["secret"]
    assert re.fullmatch(r"pumpkit_[A-Za-z0-9_-]{43}", secret)
    assert body["api_key"] == {
        "id": body["api_key"]["id"],
        "name": "Work laptop",
        "prefix": secret[:16],
        "created_at": _iso(fixed_clock()),
        "last_used_at": None,
    }
    assert body["claude_command"] == (
        "claude mcp add --scope user --transport http testapp http://localhost:5173/api/v1/mcp"
        f' --header "Authorization: Bearer {secret}"'
    )


async def test_the_list_shows_the_users_keys_oldest_first_without_secrets(
    client, subscribed, fixed_clock
):
    first = (await client.post(API_KEYS, json={"name": "Work laptop"})).json()
    fixed_clock.advance(timedelta(minutes=5))
    second = (await client.post(API_KEYS, json={"name": "  Home desktop  "})).json()

    response = await client.get(API_KEYS)

    assert response.status_code == 200
    assert response.json() == {"data": [first["api_key"], second["api_key"]]}
    assert second["api_key"]["name"] == "Home desktop"
    assert second["api_key"]["created_at"] == _iso(FIXED_NOW + timedelta(minutes=5))
    assert first["secret"] not in response.text


async def test_the_secret_is_stored_only_as_its_sha256_hash(client, subscribed, db):
    created = (await client.post(API_KEYS, json={"name": "Work laptop"})).json()

    stored = (await db.execute(select(ApiKey))).scalar_one()
    assert stored.key_hash == hashlib.sha256(created["secret"].encode()).hexdigest()


async def test_a_revoked_key_leaves_the_list(client, subscribed):
    kept = (await client.post(API_KEYS, json={"name": "Work laptop"})).json()["api_key"]
    revoked = (await client.post(API_KEYS, json={"name": "Old laptop"})).json()["api_key"]

    response = await client.delete(f"{API_KEYS}/{revoked['id']}")

    assert response.status_code == 204
    assert (await client.get(API_KEYS)).json() == {"data": [kept]}


async def test_revoking_another_users_key_is_404_and_leaves_it_working(client, subscribed, db):
    other = User(email="bob@example.com", display_name="Bob")
    db.add(other)
    await db.flush()
    db.add(
        ApiKey(
            id="api_key_bob",
            user_id=other.id,
            name="Bob's laptop",
            key_hash="bob-hash",
            prefix="pumpkit_bobbobbo",
            created_at=FIXED_NOW,
        )
    )
    await db.commit()

    response = await client.delete(f"{API_KEYS}/api_key_bob")

    assert response.status_code == 404
    assert response.json()["detail"] == "That API key doesn't exist or was already revoked."
    stored = await db.get(ApiKey, "api_key_bob")
    await db.refresh(stored)
    assert stored is not None and stored.revoked_at is None


async def test_revoking_a_key_twice_is_404(client, subscribed):
    created = (await client.post(API_KEYS, json={"name": "Work laptop"})).json()["api_key"]
    await client.delete(f"{API_KEYS}/{created['id']}")

    response = await client.delete(f"{API_KEYS}/{created['id']}")

    assert response.status_code == 404


async def test_a_user_whose_subscription_ended_can_still_list_and_revoke_keys(
    client, subscribed, db
):
    created = (await client.post(API_KEYS, json={"name": "Work laptop"})).json()["api_key"]
    subscribed.status = "canceled"
    await db.commit()

    assert (await client.get(API_KEYS)).json() == {"data": [created]}
    assert (await client.delete(f"{API_KEYS}/{created['id']}")).status_code == 204


async def test_an_eleventh_key_is_refused_until_one_is_revoked(client, subscribed):
    created = [
        (await client.post(API_KEYS, json={"name": f"Machine {i}"})).json()["api_key"]
        for i in range(10)
    ]

    refused = await client.post(API_KEYS, json={"name": "Machine 11"})

    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "You already have 10 API keys, the most you can hold. Revoke one to create another."
    )
    assert len((await client.get(API_KEYS)).json()["data"]) == 10

    await client.delete(f"{API_KEYS}/{created[0]['id']}")
    assert (await client.post(API_KEYS, json={"name": "Machine 11"})).status_code == 201


async def test_a_blank_name_is_refused(client, subscribed):
    response = await client.post(API_KEYS, json={"name": "   "})

    assert response.status_code == 422


async def test_a_key_sent_as_the_bearer_token_to_a_web_route_is_401(
    authed_client, new_browser, subscribed
):
    secret = (await authed_client.post(API_KEYS, json={"name": "Work laptop"})).json()["secret"]
    program = new_browser()
    program.headers["Authorization"] = f"Bearer {secret}"

    for response in (
        await program.get("/api/v1/users/me"),
        await program.get(API_KEYS),
        await program.post("/api/v1/refresh-token"),
    ):
        assert response.status_code == 401
    assert "refresh_token" not in program.cookies


async def test_a_user_who_isnt_subscribed_cant_create_a_key_where_plans_are_sold(client):
    response = await client.post(API_KEYS, json={"name": "Work laptop"})

    assert response.status_code == 403
    assert response.json()["detail"] == "This needs a subscription. Subscribe to continue."
    assert (await client.get(API_KEYS)).json() == {"data": []}


async def test_every_user_can_create_a_key_where_no_plans_are_sold(client, sells_no_plans):
    response = await client.post(API_KEYS, json={"name": "Work laptop"})

    assert response.status_code == 201
