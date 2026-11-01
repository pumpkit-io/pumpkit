import pytest
from sqlalchemy import select

from pumpkit.connected_apps.models import OAuthAccessToken
from pumpkit.core.security import hash_token
from tests.connected_apps.conftest import REVOKE, approved_code, exchange, refresh, register

pytestmark = pytest.mark.usefixtures("sells_no_plans")


@pytest.fixture
def app(new_browser):
    return new_browser()


@pytest.fixture
async def tokens(authed_client, app, oauth_client) -> dict[str, str]:
    code = await approved_code(authed_client, app, oauth_client)
    return (await exchange(app, oauth_client, code)).json()


async def revoke(app, client_id: str, token: str, **fields: str):
    response = await app.post(REVOKE, data={"client_id": client_id, "token": token, **fields})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response


async def test_revoking_the_refresh_token_disconnects_the_app(app, oauth_client, tokens):
    await revoke(app, oauth_client, tokens["refresh_token"])

    response = await refresh(app, oauth_client, tokens["refresh_token"])
    assert response.json()["error"] == "invalid_grant"


async def test_revoking_a_rotated_refresh_token_disconnects_the_app_too(app, oauth_client, tokens):
    rotated = (await refresh(app, oauth_client, tokens["refresh_token"])).json()

    await revoke(app, oauth_client, tokens["refresh_token"])

    assert (await refresh(app, oauth_client, rotated["refresh_token"])).status_code == 400


async def test_revoking_the_access_token_revokes_only_it(app, oauth_client, tokens, db):
    await revoke(app, oauth_client, tokens["access_token"], token_type_hint="access_token")

    access = (
        await db.execute(
            select(OAuthAccessToken).where(
                OAuthAccessToken.token_hash == hash_token(tokens["access_token"])
            )
        )
    ).scalar_one()
    assert access.revoked_at is not None
    assert (await refresh(app, oauth_client, tokens["refresh_token"])).status_code == 200


async def test_a_wrong_hint_still_finds_the_token(app, oauth_client, tokens):
    await revoke(app, oauth_client, tokens["refresh_token"], token_type_hint="access_token")

    assert (await refresh(app, oauth_client, tokens["refresh_token"])).status_code == 400


async def test_an_unknown_token_answers_200(app, oauth_client):
    await revoke(app, oauth_client, "pumpkit_rt_nope")


async def test_another_apps_token_answers_200_and_stays_valid(app, oauth_client, tokens):
    other = await register(app, "http://127.0.0.1:1/cb")

    await revoke(app, other, tokens["refresh_token"])

    assert (await refresh(app, oauth_client, tokens["refresh_token"])).status_code == 200


async def test_revoking_needs_the_app_to_authenticate(app, tokens):
    response = await app.post(
        REVOKE, data={"client_id": "oauth_client_nope", "token": tokens["refresh_token"]}
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


async def test_revoking_needs_a_token(app, oauth_client):
    response = await app.post(REVOKE, data={"client_id": oauth_client})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
