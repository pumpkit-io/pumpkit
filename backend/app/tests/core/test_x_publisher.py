import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from app.core.config import settings
from app.core.x_publisher import (
    X_AUTHORIZE_URL,
    X_REVOKE_URL,
    X_TOKEN_URL,
    X_USERS_ME_URL,
    OfficialXPublisher,
    XAccount,
    XPublisherError,
    XPublisherNotConfiguredError,
    XReconnectNeededError,
    XTokens,
    code_challenge_for,
    new_code_verifier,
)


@pytest.fixture(autouse=True)
def x_app(monkeypatch):
    monkeypatch.setattr(settings, "X_CLIENT_ID", "x-client-id")
    monkeypatch.setattr(settings, "X_CLIENT_SECRET", "x-client-secret")
    monkeypatch.setattr(settings, "X_REDIRECT_URI", "http://localhost:5173/oauth/x/callback")


def test_the_challenge_matches_the_rfc_7636_example():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"

    assert code_challenge_for(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_the_challenge_has_no_padding():
    assert "=" not in code_challenge_for("a")


def test_a_verifier_is_a_fresh_43_to_128_character_string():
    first, second = new_code_verifier(), new_code_verifier()

    assert 43 <= len(first) <= 128
    assert first != second


def test_the_authorize_url_asks_for_the_publishing_scopes_with_an_s256_challenge():
    url = OfficialXPublisher().build_authorize_url(state="the-state", code_challenge="chal")

    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == X_AUTHORIZE_URL
    assert {key: values[0] for key, values in parse_qs(parts.query).items()} == {
        "response_type": "code",
        "client_id": "x-client-id",
        "redirect_uri": "http://localhost:5173/oauth/x/callback",
        "scope": "tweet.read tweet.write users.read offline.access",
        "state": "the-state",
        "code_challenge": "chal",
        "code_challenge_method": "S256",
    }


@pytest.mark.parametrize("missing", ["X_CLIENT_ID", "X_CLIENT_SECRET", "X_REDIRECT_URI"])
def test_without_the_x_app_settings_it_fails_on_use_naming_them(monkeypatch, missing):
    monkeypatch.setattr(settings, missing, None)

    with pytest.raises(XPublisherNotConfiguredError, match="X_CLIENT_ID"):
        OfficialXPublisher().build_authorize_url(state="s", code_challenge="c")


NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
BASIC = "Basic " + base64.b64encode(b"x-client-id:x-client-secret").decode()


def _form(request: httpx.Request) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(request.content.decode()).items()}


def _token_body(**overrides) -> dict:
    body = {
        "token_type": "bearer",
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_in": 7200,
        "scope": "tweet.read tweet.write users.read offline.access",
    }
    body.update(overrides)
    return {key: value for key, value in body.items() if value is not None}


@respx.mock
async def test_exchanging_a_code_sends_it_with_the_verifier_as_a_confidential_client():
    route = respx.post(X_TOKEN_URL).mock(return_value=httpx.Response(200, json=_token_body()))

    tokens = await OfficialXPublisher().exchange_code(
        code="the-code", code_verifier="the-verifier", now=NOW
    )

    assert tokens == XTokens(
        access_token="access-1",
        refresh_token="refresh-1",
        expires_at=NOW + timedelta(seconds=7200),
        scope="tweet.read tweet.write users.read offline.access",
    )
    request = route.calls.last.request
    assert request.headers["Authorization"] == BASIC
    assert _form(request) == {
        "grant_type": "authorization_code",
        "code": "the-code",
        "code_verifier": "the-verifier",
        "redirect_uri": "http://localhost:5173/oauth/x/callback",
    }


@respx.mock
async def test_the_expiry_is_stamped_from_expires_in():
    respx.post(X_TOKEN_URL).mock(return_value=httpx.Response(200, json=_token_body(expires_in=60)))

    tokens = await OfficialXPublisher().exchange_code(code="c", code_verifier="v", now=NOW)

    assert tokens.expires_at == NOW + timedelta(seconds=60)


@respx.mock
async def test_an_exchange_without_a_refresh_token_is_refused_naming_offline_access():
    respx.post(X_TOKEN_URL).mock(
        return_value=httpx.Response(200, json=_token_body(refresh_token=None))
    )

    with pytest.raises(XReconnectNeededError, match="offline.access"):
        await OfficialXPublisher().exchange_code(code="c", code_verifier="v", now=NOW)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"error": "invalid_grant", "error_description": "bad code"}),
        httpx.Response(401, json={"error": "invalid_client"}),
    ],
)
@respx.mock
async def test_a_refused_grant_or_client_needs_a_reconnect(response):
    respx.post(X_TOKEN_URL).mock(return_value=response)

    with pytest.raises(XReconnectNeededError):
        await OfficialXPublisher().exchange_code(code="c", code_verifier="v", now=NOW)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, text="Service Unavailable"),
        httpx.Response(400, json={"error": "invalid_request"}),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"token_type": "bearer"}),
    ],
)
@respx.mock
async def test_any_other_token_failure_is_an_ordinary_error(response):
    respx.post(X_TOKEN_URL).mock(return_value=response)

    with pytest.raises(XPublisherError) as raised:
        await OfficialXPublisher().exchange_code(code="c", code_verifier="v", now=NOW)

    assert not isinstance(raised.value, XReconnectNeededError)


@respx.mock
async def test_a_network_failure_on_the_token_call_is_an_ordinary_error():
    respx.post(X_TOKEN_URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(XPublisherError) as raised:
        await OfficialXPublisher().exchange_code(code="c", code_verifier="v", now=NOW)

    assert not isinstance(raised.value, XReconnectNeededError)


@respx.mock
async def test_reading_the_account_returns_its_id_handle_and_subscription_type():
    route = respx.get(X_USERS_ME_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"id": "42", "username": "ada", "subscription_type": "Premium"}},
        )
    )

    account = await OfficialXPublisher().fetch_account(access_token="access-1")

    assert account == XAccount(user_id="42", handle="ada", subscription_type="Premium")
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer access-1"
    assert request.url.params["user.fields"] == "subscription_type"


@respx.mock
async def test_an_account_without_a_subscription_type_reads_as_none():
    respx.get(X_USERS_ME_URL).mock(
        return_value=httpx.Response(200, json={"data": {"id": "42", "username": "ada"}})
    )

    account = await OfficialXPublisher().fetch_account(access_token="access-1")

    assert account.subscription_type is None


@respx.mock
async def test_a_refused_token_when_reading_the_account_needs_a_reconnect():
    respx.get(X_USERS_ME_URL).mock(return_value=httpx.Response(401, json={"title": "Unauthorized"}))

    with pytest.raises(XReconnectNeededError):
        await OfficialXPublisher().fetch_account(access_token="access-1")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="oops"),
        httpx.Response(200, json={"data": {"username": "ada"}}),
        httpx.Response(200, text="not json"),
    ],
)
@respx.mock
async def test_an_unreadable_account_is_an_ordinary_error(response):
    respx.get(X_USERS_ME_URL).mock(return_value=response)

    with pytest.raises(XPublisherError) as raised:
        await OfficialXPublisher().fetch_account(access_token="access-1")

    assert not isinstance(raised.value, XReconnectNeededError)


@respx.mock
async def test_revoking_sends_the_refresh_token_as_a_confidential_client():
    route = respx.post(X_REVOKE_URL).mock(return_value=httpx.Response(200, json={"revoked": True}))

    await OfficialXPublisher().revoke(token="refresh-1", token_type_hint="refresh_token")

    request = route.calls.last.request
    assert request.headers["Authorization"] == BASIC
    assert _form(request) == {"token": "refresh-1", "token_type_hint": "refresh_token"}


@pytest.mark.parametrize(
    "mock",
    [
        {"return_value": httpx.Response(503, text="down")},
        {"side_effect": httpx.ConnectError("refused")},
    ],
)
@respx.mock
async def test_a_failed_revoke_is_an_error(mock):
    respx.post(X_REVOKE_URL).mock(**mock)

    with pytest.raises(XPublisherError):
        await OfficialXPublisher().revoke(token="refresh-1", token_type_hint="refresh_token")
