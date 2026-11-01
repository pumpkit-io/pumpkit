import base64
from datetime import timedelta
from urllib.parse import quote_plus

import pytest
from sqlalchemy import select

from pumpkit.connected_apps.models import AppConnection
from tests.connected_apps.conftest import (
    MCP_URL,
    REDIRECT,
    TOKEN,
    VERIFIER,
    approved_code,
    exchange,
    query,
    refresh,
    register,
    start_for,
)

pytestmark = pytest.mark.usefixtures("sells_no_plans")


@pytest.fixture
def app(new_browser):
    """The app's own HTTP client, which holds no web Session."""
    return new_browser()


async def test_the_app_exchanges_its_code_for_an_access_and_a_refresh_token(
    authed_client, app, oauth_client
):
    code = await approved_code(authed_client, app, oauth_client)

    response = await exchange(app, oauth_client, code)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    body = response.json()
    assert body.pop("access_token").startswith("pumpkit_at_")
    assert body.pop("refresh_token").startswith("pumpkit_rt_")
    assert body == {"token_type": "Bearer", "expires_in": 3600, "scope": "pumpkit"}


async def refused(response, error: str, status_code: int = 400) -> None:
    assert response.status_code == status_code, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    body = response.json()
    assert body["error"] == error
    assert set(body) == {"error", "error_description"}


async def test_a_wrong_code_verifier_is_refused(authed_client, app, oauth_client):
    code = await approved_code(authed_client, app, oauth_client)

    response = await exchange(app, oauth_client, code, code_verifier="x" * 43)

    await refused(response, "invalid_grant")


async def test_a_missing_code_verifier_is_refused(authed_client, app, oauth_client):
    code = await approved_code(authed_client, app, oauth_client)

    response = await app.post(
        TOKEN,
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_client,
            "code": code,
            "redirect_uri": REDIRECT,
        },
    )

    await refused(response, "invalid_grant")


async def test_a_redirect_uri_other_than_the_one_sent_to_authorize_is_refused(
    authed_client, app, oauth_client
):
    code = await approved_code(authed_client, app, oauth_client)

    response = await exchange(app, oauth_client, code, redirect_uri="http://127.0.0.1:9/callback")

    await refused(response, "invalid_grant")


async def test_the_redirect_uri_sent_to_authorize_must_be_sent_again(
    authed_client, app, oauth_client
):
    code = await approved_code(authed_client, app, oauth_client)

    response = await app.post(
        TOKEN,
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_client,
            "code": code,
            "code_verifier": VERIFIER,
        },
    )

    await refused(response, "invalid_grant")


async def test_an_app_that_sent_no_redirect_uri_to_authorize_needs_none(
    authed_client, app, oauth_client
):
    started = await start_for(app, oauth_client)
    request_id = query(started.headers["location"])["request"]
    approved = await authed_client.post(f"/api/v1/oauth/authorizations/{request_id}/approve")
    code = query(approved.json()["redirect_url"])["code"]

    response = await app.post(
        TOKEN,
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_client,
            "code": code,
            "code_verifier": VERIFIER,
        },
    )

    assert response.status_code == 200, response.text


async def test_a_code_still_works_just_before_two_minutes(authed_client, app, oauth_client, clock):
    code = await approved_code(authed_client, app, oauth_client)
    clock.advance(timedelta(minutes=1, seconds=59))

    assert (await exchange(app, oauth_client, code)).status_code == 200


async def test_an_expired_code_is_refused(authed_client, app, oauth_client, clock):
    code = await approved_code(authed_client, app, oauth_client)
    clock.advance(timedelta(minutes=2))

    await refused(await exchange(app, oauth_client, code), "invalid_grant")


async def test_an_unknown_code_is_refused(app, oauth_client):
    await refused(await exchange(app, oauth_client, "nope"), "invalid_grant")


async def test_another_apps_code_is_refused(authed_client, app, oauth_client):
    code = await approved_code(authed_client, app, oauth_client)
    other = await register(app, REDIRECT)

    await refused(await exchange(app, other, code), "invalid_grant")


async def test_a_resource_other_than_the_mcp_url_is_refused(authed_client, app, oauth_client):
    code = await approved_code(authed_client, app, oauth_client)

    response = await exchange(app, oauth_client, code, resource="https://evil.example/mcp")

    await refused(response, "invalid_target")


async def test_the_mcp_url_is_accepted_as_the_resource(authed_client, app, oauth_client):
    code = await approved_code(authed_client, app, oauth_client)

    assert (await exchange(app, oauth_client, code, resource=f"{MCP_URL}/")).status_code == 200


async def test_using_a_code_twice_disconnects_the_app(authed_client, app, oauth_client, caplog):
    code = await approved_code(authed_client, app, oauth_client)
    first = (await exchange(app, oauth_client, code)).json()

    await refused(await exchange(app, oauth_client, code), "invalid_grant")

    await refused(await refresh(app, oauth_client, first["refresh_token"]), "invalid_grant")
    assert any(
        record.levelname == "ERROR" and "reuse" in record.getMessage() for record in caplog.records
    )


async def test_a_suspended_user_cannot_exchange_a_code(
    authed_client, app, oauth_client, suspend_user, user
):
    code = await approved_code(authed_client, app, oauth_client)
    await suspend_user(user.email)

    await refused(await exchange(app, oauth_client, code), "invalid_grant")


async def test_a_disconnected_apps_code_is_refused(authed_client, app, oauth_client, db, clock):
    code = await approved_code(authed_client, app, oauth_client)
    connection = (await db.execute(select(AppConnection))).scalar_one()
    connection.revoked_at = clock()
    await db.commit()

    await refused(await exchange(app, oauth_client, code), "invalid_grant")


async def test_an_unknown_app_is_refused(app):
    await refused(await exchange(app, "oauth_client_nope", "nope"), "invalid_client", 401)


async def test_another_grant_type_is_refused(app, oauth_client):
    response = await app.post(TOKEN, data={"grant_type": "password", "client_id": oauth_client})

    await refused(response, "unsupported_grant_type")


async def test_a_missing_grant_type_is_refused(app, oauth_client):
    await refused(await app.post(TOKEN, data={"client_id": oauth_client}), "invalid_request")


async def test_a_json_body_gets_an_oauth_error_not_a_detail(app, oauth_client):
    response = await app.post(TOKEN, json={"grant_type": "authorization_code"})

    await refused(response, "invalid_client", 401)


async def test_a_field_sent_twice_is_refused(authed_client, app, oauth_client):
    code = await approved_code(authed_client, app, oauth_client)

    response = await app.post(
        TOKEN,
        content=f"grant_type=authorization_code&client_id={oauth_client}&code={code}&code=x",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    await refused(response, "invalid_request")


@pytest.fixture
def connected(authed_client, app, oauth_client):
    """Connect `oauth_client` for `user` and return its first token response."""

    async def _connected() -> dict[str, str]:
        code = await approved_code(authed_client, app, oauth_client)
        response = await exchange(app, oauth_client, code)
        assert response.status_code == 200, response.text
        return response.json()

    return _connected


async def test_refreshing_rotates_the_refresh_token(app, oauth_client, connected):
    first = await connected()

    response = await refresh(app, oauth_client, first["refresh_token"])

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["refresh_token"] != first["refresh_token"]
    assert body["access_token"] != first["access_token"]
    assert (body["token_type"], body["expires_in"], body["scope"]) == ("Bearer", 3600, "pumpkit")
    assert (await refresh(app, oauth_client, body["refresh_token"])).status_code == 200


async def test_a_rotated_refresh_token_presented_again_within_two_minutes_gets_a_fresh_pair(
    app, oauth_client, connected, clock
):
    first = await connected()
    rotated = (await refresh(app, oauth_client, first["refresh_token"])).json()
    clock.advance(timedelta(minutes=2))

    retried = await refresh(app, oauth_client, first["refresh_token"])

    assert retried.status_code == 200, retried.text
    fresh = retried.json()
    assert fresh["refresh_token"] not in {first["refresh_token"], rotated["refresh_token"]}
    assert (await refresh(app, oauth_client, fresh["refresh_token"])).status_code == 200
    assert (await refresh(app, oauth_client, rotated["refresh_token"])).status_code == 200


async def test_a_rotated_refresh_token_presented_after_two_minutes_disconnects_the_app(
    app, oauth_client, connected, clock, caplog
):
    first = await connected()
    rotated = (await refresh(app, oauth_client, first["refresh_token"])).json()
    clock.advance(timedelta(minutes=2, seconds=1))

    await refused(await refresh(app, oauth_client, first["refresh_token"]), "invalid_grant")

    await refused(await refresh(app, oauth_client, rotated["refresh_token"]), "invalid_grant")
    assert any(
        record.levelname == "ERROR" and "reuse" in record.getMessage() for record in caplog.records
    )


async def test_a_refresh_token_still_works_just_before_ninety_days(
    app, oauth_client, connected, clock
):
    first = await connected()
    clock.advance(timedelta(days=90) - timedelta(seconds=1))

    assert (await refresh(app, oauth_client, first["refresh_token"])).status_code == 200


async def test_an_expired_refresh_token_is_refused(app, oauth_client, connected, clock):
    first = await connected()
    clock.advance(timedelta(days=90))

    await refused(await refresh(app, oauth_client, first["refresh_token"]), "invalid_grant")


async def test_an_unknown_refresh_token_is_refused(app, oauth_client):
    await refused(await refresh(app, oauth_client, "pumpkit_rt_nope"), "invalid_grant")


async def test_a_missing_refresh_token_is_refused(app, oauth_client):
    response = await app.post(
        TOKEN, data={"grant_type": "refresh_token", "client_id": oauth_client}
    )

    await refused(response, "invalid_request")


async def test_another_apps_refresh_token_is_refused(app, oauth_client, connected):
    first = await connected()
    other = await register(app, REDIRECT)

    await refused(await refresh(app, other, first["refresh_token"]), "invalid_grant")


async def test_refreshing_for_another_resource_is_refused(app, oauth_client, connected):
    first = await connected()

    response = await refresh(
        app, oauth_client, first["refresh_token"], resource="https://evil.example/mcp"
    )

    await refused(response, "invalid_target")


async def test_refreshing_ignores_the_scope_sent(app, oauth_client, connected):
    first = await connected()

    response = await refresh(app, oauth_client, first["refresh_token"], scope="openid admin")

    assert response.json()["scope"] == "pumpkit"


async def test_a_suspended_user_cannot_refresh(app, oauth_client, connected, suspend_user, user):
    first = await connected()
    await suspend_user(user.email)

    await refused(await refresh(app, oauth_client, first["refresh_token"]), "invalid_grant")


async def test_a_suspended_user_gets_no_fresh_pair_within_the_grace(
    app, oauth_client, connected, suspend_user, user
):
    first = await connected()
    await refresh(app, oauth_client, first["refresh_token"])
    await suspend_user(user.email)

    await refused(await refresh(app, oauth_client, first["refresh_token"]), "invalid_grant")


@pytest.fixture
def secret_client(app):
    """Register an app with a secret, and return its id and secret."""

    async def _register(method: str = "client_secret_basic") -> tuple[str, str]:
        response = await app.post(
            "/api/v1/oauth/register",
            json={"redirect_uris": [REDIRECT], "token_endpoint_auth_method": method},
        )
        body = response.json()
        return body["client_id"], body["client_secret"]

    return _register


def basic(client_id: str, secret: str) -> dict[str, str]:
    # RFC 6749 section 2.3.1: each part form-encoded, then joined and base64-encoded.
    joined = f"{quote_plus(client_id)}:{quote_plus(secret)}"
    return {"Authorization": f"Basic {base64.b64encode(joined.encode()).decode()}"}


async def code_for(authed_client, app, client_id: str) -> dict[str, str]:
    """A token request body for a fresh code, with no client authentication in it."""
    return {
        "grant_type": "authorization_code",
        "code": await approved_code(authed_client, app, client_id),
        "redirect_uri": REDIRECT,
        "code_verifier": VERIFIER,
    }


async def test_a_secret_app_authenticates_with_http_basic(authed_client, app, secret_client):
    client_id, secret = await secret_client()

    response = await app.post(
        TOKEN, data=await code_for(authed_client, app, client_id), headers=basic(client_id, secret)
    )

    assert response.status_code == 200, response.text


async def test_a_secret_app_authenticates_with_its_secret_in_the_body(
    authed_client, app, secret_client
):
    client_id, secret = await secret_client("client_secret_post")
    body = await code_for(authed_client, app, client_id)

    response = await app.post(TOKEN, data={**body, "client_id": client_id, "client_secret": secret})

    assert response.status_code == 200, response.text


async def test_a_basic_app_may_send_its_secret_in_the_body_too(authed_client, app, secret_client):
    client_id, secret = await secret_client("client_secret_basic")
    body = await code_for(authed_client, app, client_id)

    response = await app.post(TOKEN, data={**body, "client_id": client_id, "client_secret": secret})

    assert response.status_code == 200, response.text


async def test_a_secret_app_without_its_secret_is_refused(authed_client, app, secret_client):
    client_id, _ = await secret_client()
    body = await code_for(authed_client, app, client_id)

    response = await app.post(TOKEN, data={**body, "client_id": client_id})

    await refused(response, "invalid_client", 401)
    assert "www-authenticate" not in response.headers


async def test_a_wrong_secret_over_basic_is_refused_with_a_basic_challenge(
    authed_client, app, secret_client
):
    client_id, _ = await secret_client()

    response = await app.post(
        TOKEN,
        data=await code_for(authed_client, app, client_id),
        headers=basic(client_id, "pumpkit_cs_wrong"),
    )

    await refused(response, "invalid_client", 401)
    assert response.headers["www-authenticate"] == 'Basic realm="pumpkit"'


async def test_a_malformed_basic_header_is_refused(app):
    response = await app.post(
        TOKEN, data={"grant_type": "refresh_token"}, headers={"Authorization": "Basic !!!"}
    )

    await refused(response, "invalid_client", 401)
    assert response.headers["www-authenticate"] == 'Basic realm="pumpkit"'


async def test_basic_and_a_different_client_id_in_the_body_are_refused(
    authed_client, app, secret_client, oauth_client
):
    client_id, secret = await secret_client()
    body = await code_for(authed_client, app, client_id)

    response = await app.post(
        TOKEN, data={**body, "client_id": oauth_client}, headers=basic(client_id, secret)
    )

    await refused(response, "invalid_client", 401)


async def test_a_public_apps_empty_secret_is_ignored(authed_client, app, oauth_client):
    code = await approved_code(authed_client, app, oauth_client)

    response = await exchange(app, oauth_client, code, client_secret="")

    assert response.status_code == 200, response.text


async def test_a_public_app_may_use_basic_with_an_empty_secret(authed_client, app, oauth_client):
    body = await code_for(authed_client, app, oauth_client)

    response = await app.post(TOKEN, data=body, headers=basic(oauth_client, ""))

    assert response.status_code == 200, response.text


async def test_the_token_endpoint_allows_three_hundred_requests_a_minute_per_address(app):
    for _ in range(300):
        assert (await app.post(TOKEN, data={})).status_code == 401

    response = await app.post(TOKEN, data={})

    await refused(response, "temporarily_unavailable", 429)
    assert "retry-after" in response.headers
