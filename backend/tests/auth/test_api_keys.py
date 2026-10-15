"""API key management through the `/api-keys` routes, authenticated by the browser Session."""

import hashlib
import re
from datetime import timedelta

from sqlalchemy import select

from pumpkit.auth.models import ApiKey
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
        "claude mcp add --transport http testapp http://localhost:5173/api/v1/mcp"
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


async def test_a_user_who_isnt_subscribed_cant_create_a_key_where_plans_are_sold(client):
    response = await client.post(API_KEYS, json={"name": "Work laptop"})

    assert response.status_code == 403
    assert response.json()["detail"] == "This needs a Subscription. Subscribe to continue."
    assert (await client.get(API_KEYS)).json() == {"data": []}


async def test_every_user_can_create_a_key_where_no_plans_are_sold(client, sells_no_plans):
    response = await client.post(API_KEYS, json={"name": "Work laptop"})

    assert response.status_code == 201
