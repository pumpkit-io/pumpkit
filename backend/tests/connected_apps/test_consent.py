from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest_asyncio
from sqlalchemy import select

from pumpkit.connected_apps.models import AppConnection, OAuthAuthorization
from tests.connected_apps.conftest import MCP_URL, REDIRECT

AUTHORIZE = "/api/v1/oauth/authorize"
ISSUER = "http://localhost:5173"


def details(request_id: str) -> str:
    return f"/api/v1/oauth/authorizations/{request_id}"


def query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


@pytest_asyncio.fixture
async def start(new_browser, authorize_params):
    """Start another authorization from the app, and return the consent request's id."""

    async def _start(**override: str) -> str:
        response = await new_browser().get(AUTHORIZE, params={**authorize_params, **override})
        return query(response.headers["location"])["request"]

    return _start


@pytest_asyncio.fixture
async def request_id(start) -> str:
    return await start()


async def test_the_details_name_the_app_and_where_it_sends_the_user(authed_client, new_browser):
    registered = await new_browser().post(
        "/api/v1/oauth/register",
        json={"redirect_uris": ["https://claude.ai/cb"], "client_name": "Claude"},
    )
    started = await new_browser().get(
        AUTHORIZE,
        params={
            "client_id": registered.json()["client_id"],
            "response_type": "code",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
        },
    )
    web_request = query(started.headers["location"])["request"]

    response = await authed_client.get(details(web_request))

    assert response.status_code == 200
    body = response.json()
    assert body.pop("expires_at")
    assert body == {
        "client": {
            "name": "Claude",
            "verified_domain": None,
            "redirect_host": "claude.ai",
            "is_local": False,
        },
        "scope": "pumpkit",
    }


async def test_an_app_on_the_users_computer_has_no_redirect_host(authed_client, request_id):
    body = (await authed_client.get(details(request_id))).json()

    assert body["client"] == {
        "name": "Gemini CLI",
        "verified_domain": None,
        "redirect_host": None,
        "is_local": True,
    }


async def test_a_custom_scheme_redirect_is_local_too(authed_client, new_browser):
    registered = await new_browser().post(
        "/api/v1/oauth/register",
        json={"redirect_uris": ["cursor://anysphere/cb"], "token_endpoint_auth_method": "none"},
    )
    started = await new_browser().get(
        AUTHORIZE,
        params={
            "client_id": registered.json()["client_id"],
            "response_type": "code",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
        },
    )

    body = (await authed_client.get(details(query(started.headers["location"])["request"]))).json()

    assert body["client"]["is_local"] is True
    assert body["client"]["redirect_host"] is None


async def test_the_details_need_a_signed_in_user(new_browser, request_id):
    response = await new_browser().get(details(request_id))

    assert response.status_code == 401


async def test_an_unknown_request_is_404(authed_client):
    response = await authed_client.get(details("nope"))

    assert response.status_code == 404


async def test_an_expired_request_is_404(authed_client, request_id, clock):
    clock.advance(timedelta(minutes=31))

    assert (await authed_client.get(details(request_id))).status_code == 404


async def test_a_request_still_valid_at_thirty_minutes_can_be_approved(
    authed_client, request_id, clock, sells_no_plans
):
    clock.advance(timedelta(minutes=29))

    response = await authed_client.post(f"{details(request_id)}/approve")

    assert response.status_code == 200


async def test_approving_needs_a_subscription(authed_client, request_id):
    response = await authed_client.post(f"{details(request_id)}/approve")

    assert response.status_code == 403


async def test_approving_is_allowed_on_an_instance_that_sells_no_plans(
    authed_client, request_id, sells_no_plans
):
    response = await authed_client.post(f"{details(request_id)}/approve")

    assert response.status_code == 200


async def test_approving_hands_the_app_a_code_with_state_and_issuer(
    authed_client, request_id, subscribed, db, user
):
    response = await authed_client.post(f"{details(request_id)}/approve")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    redirect_url = response.json()["redirect_url"]
    assert redirect_url.startswith(f"{REDIRECT}?")
    received = query(redirect_url)
    assert set(received) == {"code", "state", "iss"}
    assert (received["state"], received["iss"]) == ("xyz", ISSUER)
    authorization = await db.get(OAuthAuthorization, request_id)
    assert authorization is not None
    assert authorization.approved is True
    assert authorization.user_id == user.id
    connection = (await db.execute(select(AppConnection))).scalar_one()
    assert authorization.app_connection_id == connection.id
    assert (connection.user_id, connection.scope, connection.resource) == (
        user.id,
        "pumpkit",
        MCP_URL,
    )


async def test_the_code_comes_back_in_the_redirect_uris_own_query(
    authed_client, new_browser, subscribed
):
    registered = await new_browser().post(
        "/api/v1/oauth/register",
        json={"redirect_uris": ["https://app.example/cb?tenant=1"]},
    )
    started = await new_browser().get(
        AUTHORIZE,
        params={
            "client_id": registered.json()["client_id"],
            "response_type": "code",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
        },
    )

    response = await authed_client.post(
        f"{details(query(started.headers['location'])['request'])}/approve"
    )

    received = query(response.json()["redirect_url"])
    assert received["tenant"] == "1"
    assert "code" in received
    assert "state" not in received


async def test_approving_twice_is_404(authed_client, request_id, subscribed):
    await authed_client.post(f"{details(request_id)}/approve")

    response = await authed_client.post(f"{details(request_id)}/approve")

    assert response.status_code == 404
    assert (await authed_client.get(details(request_id))).status_code == 404


async def test_approving_an_expired_request_is_404(authed_client, request_id, subscribed, clock):
    clock.advance(timedelta(minutes=31))

    assert (await authed_client.post(f"{details(request_id)}/approve")).status_code == 404


async def test_a_second_approval_for_the_same_app_reuses_the_connection(
    authed_client, start, subscribed, db
):
    for _ in range(2):
        await authed_client.post(f"{details(await start())}/approve")

    assert len((await db.execute(select(AppConnection))).scalars().all()) == 1
    authorizations = (await db.execute(select(OAuthAuthorization))).scalars().all()
    assert len({row.app_connection_id for row in authorizations}) == 1


async def test_a_disconnected_apps_next_approval_makes_a_new_connection(
    authed_client, start, subscribed, db, clock
):
    await authed_client.post(f"{details(await start())}/approve")
    connection = (await db.execute(select(AppConnection))).scalar_one()
    connection.revoked_at = clock()
    await db.commit()

    await authed_client.post(f"{details(await start())}/approve")

    assert len((await db.execute(select(AppConnection))).scalars().all()) == 2


async def test_denying_tells_the_app_the_user_refused(authed_client, request_id, db):
    response = await authed_client.post(f"{details(request_id)}/deny")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    received = query(response.json()["redirect_url"])
    assert received == {"error": "access_denied", "state": "xyz", "iss": ISSUER} | {
        "error_description": received["error_description"]
    }
    assert (await db.execute(select(AppConnection))).first() is None
    assert (await authed_client.post(f"{details(request_id)}/deny")).status_code == 404
    assert (await authed_client.get(details(request_id))).status_code == 404


async def test_a_denied_request_cannot_be_approved(authed_client, request_id, subscribed):
    await authed_client.post(f"{details(request_id)}/deny")

    assert (await authed_client.post(f"{details(request_id)}/approve")).status_code == 404


async def test_denying_needs_no_subscription(authed_client, request_id):
    assert (await authed_client.post(f"{details(request_id)}/deny")).status_code == 200


async def test_approving_is_limited_to_twenty_a_minute_per_user(
    authed_client, start, sells_no_plans
):
    for _ in range(20):
        assert (await authed_client.post(f"{details(await start())}/approve")).status_code == 200

    response = await authed_client.post(f"{details(await start())}/approve")

    assert response.status_code == 429
    assert "Retry-After" in response.headers
