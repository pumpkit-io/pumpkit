from datetime import timedelta

import pytest
from sqlalchemy import select

from pumpkit.connected_apps.models import OAuthAuthorization
from tests.oauth_app import (
    AUTHORIZE,
    CONSENT,
    ISSUER,
    MCP_URL,
    REDIRECT,
    query,
    register,
    start_for,
)


@pytest.fixture
def browser(new_browser):
    return new_browser()


async def test_a_valid_request_is_stored_and_sent_to_the_consent_page(
    browser, authorize_params, db
):
    response = await browser.get(AUTHORIZE, params=authorize_params)

    assert response.status_code == 303
    assert response.headers["cache-control"] == "no-store"
    location = response.headers["location"]
    assert location.startswith(f"{CONSENT}?request=")
    stored = (await db.execute(select(OAuthAuthorization))).scalar_one()
    assert query(location) == {"request": stored.id}
    assert stored.client_id == authorize_params["client_id"]
    assert stored.redirect_uri == REDIRECT
    assert stored.redirect_uri_was_sent is True
    assert stored.state == "xyz"
    assert stored.resource == MCP_URL
    assert stored.approved is None


async def test_a_form_post_is_answered_with_a_303_too(browser, authorize_params):
    response = await browser.post(AUTHORIZE, data=authorize_params)

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"{CONSENT}?request=")


async def test_unknown_scopes_are_dropped(browser, authorize_params, db):
    authorize_params["scope"] = "openid offline_access pumpkit profile"

    await browser.get(AUTHORIZE, params=authorize_params)

    assert (await db.execute(select(OAuthAuthorization))).scalar_one().scope == "pumpkit"


async def test_the_mcp_url_is_assumed_when_resource_is_left_out_and_accepted_with_a_slash(
    browser, authorize_params, db
):
    await browser.get(AUTHORIZE, params=authorize_params)
    await browser.get(AUTHORIZE, params={**authorize_params, "resource": MCP_URL + "/"})

    stored = (await db.execute(select(OAuthAuthorization))).scalars().all()
    assert [row.resource for row in stored] == [MCP_URL, MCP_URL]


async def test_an_omitted_redirect_uri_is_the_only_registered_one(browser, authorize_params, db):
    del authorize_params["redirect_uri"]

    response = await browser.get(AUTHORIZE, params=authorize_params)

    assert response.status_code == 303
    stored = (await db.execute(select(OAuthAuthorization))).scalar_one()
    assert (stored.redirect_uri, stored.redirect_uri_was_sent) == (REDIRECT, False)


async def test_a_loopback_redirect_may_use_another_port(browser, authorize_params, db):
    authorize_params["redirect_uri"] = "http://127.0.0.1:51234/callback"

    await browser.get(AUTHORIZE, params=authorize_params)

    stored = (await db.execute(select(OAuthAuthorization))).scalar_one()
    assert stored.redirect_uri == "http://127.0.0.1:51234/callback"


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"client_id": "oauth_client_unknown"}, "invalid_client"),
        ({"client_id": None}, "invalid_client"),
        ({"client_id": "bad\x00id"}, "invalid_client"),
        ({"redirect_uri": "http://127.0.0.1:33418/other"}, "invalid_redirect_uri"),
        ({"redirect_uri": "https://evil.example/cb"}, "invalid_redirect_uri"),
        (
            {"redirect_uri": "http://127.0.0.1:33418/callback\\@evil.example"},
            "invalid_redirect_uri",
        ),
        ({"redirect_uri": "http://127.0.0.1:33418/callback\r\nX: y"}, "invalid_redirect_uri"),
        ({"redirect_uri": "http://127.0.0.1:33418/callbäck"}, "invalid_redirect_uri"),
    ],
)
async def test_an_untrusted_request_goes_to_the_consent_page_and_never_to_the_client(
    browser, authorize_params, db, override, error
):
    params = {**authorize_params, **override}
    params = {key: value for key, value in params.items() if value is not None}

    response = await browser.get(AUTHORIZE, params=params)

    assert response.status_code == 303
    assert response.headers["location"] == f"{CONSENT}?error={error}"
    assert (await db.execute(select(OAuthAuthorization))).first() is None


async def test_an_omitted_redirect_uri_is_refused_when_the_client_registered_two(browser):
    client_id = await register(browser, REDIRECT, "cursor://app/callback")

    response = await start_for(browser, client_id)

    assert response.headers["location"] == f"{CONSENT}?error=invalid_redirect_uri"


@pytest.mark.parametrize(
    ("override", "error"),
    [
        ({"response_type": "token"}, "unsupported_response_type"),
        ({"response_type": None}, "invalid_request"),
        ({"code_challenge": None}, "invalid_request"),
        ({"code_challenge": "short"}, "invalid_request"),
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"code_challenge_method": None}, "invalid_request"),
        ({"resource": "https://other.example/mcp"}, "invalid_target"),
        ({"state": "s" * 2049}, "invalid_request"),
        ({"state": "a\x00b"}, "invalid_request"),
    ],
)
async def test_a_trusted_request_with_a_defect_redirects_to_the_client_with_the_error(
    browser, authorize_params, db, override, error
):
    params = {**authorize_params, **override}
    params = {key: value for key, value in params.items() if value is not None}

    response = await browser.get(AUTHORIZE, params=params)

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(f"{REDIRECT}?")
    received = query(location)
    assert received["error"] == error
    assert received["error_description"]
    assert received["iss"] == ISSUER
    assert received.get("state") == (None if "state" in override else "xyz")
    assert (await db.execute(select(OAuthAuthorization))).first() is None


async def test_state_is_checked_after_the_other_parameters_and_is_not_echoed_when_invalid(
    browser, authorize_params
):
    authorize_params.update(state="a\x00b", response_type="token")

    response = await browser.get(AUTHORIZE, params=authorize_params)

    received = query(response.headers["location"])
    assert received["error"] == "unsupported_response_type"
    assert "state" not in received


async def test_a_repeated_resource_is_refused(browser, authorize_params):
    response = await browser.get(
        AUTHORIZE, params=[*authorize_params.items(), ("resource", MCP_URL), ("resource", MCP_URL)]
    )

    assert query(response.headers["location"])["error"] == "invalid_target"


async def test_a_state_with_non_ascii_text_comes_back_encoded(browser, authorize_params):
    authorize_params.update(state="état ✓", response_type="token")

    response = await browser.get(AUTHORIZE, params=authorize_params)

    location = response.headers["location"]
    assert location.isascii()
    assert query(location)["state"] == "état ✓"


async def test_error_parameters_merge_into_the_redirect_uris_own_query(browser):
    client_id = await register(browser, "https://app.example/cb?team=1")

    response = await start_for(browser, client_id, response_type="token")

    received = query(response.headers["location"])
    assert received["team"] == "1"
    assert received["error"] == "unsupported_response_type"


async def test_a_redirect_uri_with_an_empty_authority_comes_back_byte_for_byte(browser):
    client_id = await register(browser, "com.example.app:///cb")

    response = await start_for(browser, client_id, response_type="token")

    assert response.headers["location"].startswith("com.example.app:///cb?error=")


async def test_authorize_is_limited_to_sixty_requests_a_minute(browser, authorize_params):
    for _ in range(60):
        assert (await browser.get(AUTHORIZE, params=authorize_params)).status_code == 303

    response = await browser.get(AUTHORIZE, params=authorize_params)

    assert response.status_code == 429
    assert response.json()["error"] == "temporarily_unavailable"


async def test_starting_an_authorization_purges_requests_older_than_a_day(
    browser, authorize_params, db, clock
):
    first = await browser.get(AUTHORIZE, params=authorize_params)
    clock.advance(timedelta(days=1, minutes=1))

    second = await browser.get(AUTHORIZE, params=authorize_params)

    stored = (await db.execute(select(OAuthAuthorization.id))).scalars().all()
    assert query(first.headers["location"])["request"] not in stored
    assert stored == [query(second.headers["location"])["request"]]
