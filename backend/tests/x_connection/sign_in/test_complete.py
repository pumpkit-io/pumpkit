from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from pumpkit.auth.models import User
from pumpkit.core.config import settings
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.service import save_connection
from pumpkit.x_connection.x_publisher import (
    X_SIGN_IN_SCOPES,
    XPublisherError,
    XReconnectNeededError,
)


async def begin(browser):
    response = await browser.get("/api/v1/login/x")
    assert response.status_code == 200
    return parse_qs(urlsplit(response.json()["url"]).query)["state"][0]


async def complete(browser, state):
    return await browser.post(
        "/api/v1/login/x/complete", json={"state": state, "code": "valid-code"}
    )


async def profile(browser, response):
    assert response.status_code == 200, response.text
    result = await browser.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
    )
    assert result.status_code == 200
    return result.json()


async def test_first_x_sign_in_starts_a_session_for_the_authenticated_x_account(
    sign_in_browser, fake_x_publisher
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    state = await begin(sign_in_browser)

    response = await complete(sign_in_browser, state)

    me = await profile(sign_in_browser, response)
    assert me["email"] == "ada@example.com"
    assert me["first_name"] == "Ada"
    assert "refresh_token" in sign_in_browser.cookies
    assert "x_sign_in_browser" not in sign_in_browser.cookies
    assert response.headers["cache-control"] == "no-store"


async def test_returning_x_id_updates_contact_but_keeps_account_and_edited_name(
    sign_in_browser, fake_x_publisher
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    first = await complete(sign_in_browser, await begin(sign_in_browser))
    original = await profile(sign_in_browser, first)
    edited = await sign_in_browser.patch(
        "/api/v1/users/me",
        json={"first_name": "My name", "last_name": "Here"},
        headers={"Authorization": f"Bearer {first.json()['access_token']}"},
    )
    assert edited.status_code == 200
    fake_x_publisher.account = replace(
        fake_x_publisher.account,
        handle="renamed",
        confirmed_email="new@example.org",
        display_name="Changed on X",
    )

    returned = await profile(
        sign_in_browser, await complete(sign_in_browser, await begin(sign_in_browser))
    )

    assert returned["id"] == original["id"]
    assert returned["email"] == "new@example.org"
    assert returned["first_name"] == "My name"
    assert returned["last_name"] == "Here"


async def test_distinct_x_accounts_sharing_email_open_separate_accounts(
    sign_in_browser, fake_x_publisher
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    original = await profile(
        sign_in_browser, await complete(sign_in_browser, await begin(sign_in_browser))
    )
    fake_x_publisher.account = replace(fake_x_publisher.account, user_id="2002", handle="other")

    other = await profile(
        sign_in_browser, await complete(sign_in_browser, await begin(sign_in_browser))
    )

    assert other["email"] == original["email"]
    assert other["id"] != original["id"]


async def test_an_x_account_does_not_inherit_a_legacy_account_by_email(
    sign_in_browser, fake_x_publisher, legacy_user
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    fake_x_publisher.account = replace(fake_x_publisher.account, confirmed_email=legacy_user.email)

    signed_in = await profile(
        sign_in_browser, await complete(sign_in_browser, await begin(sign_in_browser))
    )

    assert signed_in["id"] != legacy_user.id
    assert signed_in["email"] == legacy_user.email


async def test_expired_attempt_cannot_issue_a_session_or_call_x(
    sign_in_browser, fake_x_publisher, fixed_clock
):
    state = await begin(sign_in_browser)
    fixed_clock.advance(timedelta(minutes=10))

    response = await complete(sign_in_browser, state)

    assert response.status_code == 400
    assert response.json()["detail"] == "x_authorization_invalid"
    assert fake_x_publisher.exchanges == []
    assert "refresh_token" not in sign_in_browser.cookies


async def test_a_successful_attempt_cannot_be_replayed(sign_in_browser, fake_x_publisher):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    state = await begin(sign_in_browser)
    secret = sign_in_browser.cookies["x_sign_in_browser"]
    assert (await complete(sign_in_browser, state)).status_code == 200
    sign_in_browser.cookies.set("x_sign_in_browser", secret)

    response = await complete(sign_in_browser, state)

    assert response.status_code == 400
    assert len(fake_x_publisher.exchanges) == 1


async def test_a_failed_provider_exchange_also_spends_the_attempt(
    sign_in_browser, fake_x_publisher
):
    state = await begin(sign_in_browser)
    secret = sign_in_browser.cookies["x_sign_in_browser"]
    fake_x_publisher.fail_exchange = XPublisherError("X unreachable")

    response = await complete(sign_in_browser, state)

    assert response.status_code == 502
    assert response.json()["detail"] == "x_provider_failed"
    assert "refresh_token" not in sign_in_browser.cookies
    assert "x_sign_in_browser" not in sign_in_browser.cookies
    fake_x_publisher.fail_exchange = None
    sign_in_browser.cookies.set("x_sign_in_browser", secret)
    assert (await complete(sign_in_browser, state)).status_code == 400
    assert len(fake_x_publisher.exchanges) == 1


async def test_changed_contact_outside_allowlist_cannot_alter_the_account(
    sign_in_browser, fake_x_publisher, monkeypatch
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    first = await complete(sign_in_browser, await begin(sign_in_browser))
    old_access = first.json()["access_token"]
    original = await profile(sign_in_browser, first)
    monkeypatch.setattr(settings, "SIGN_UP_ALLOWLIST", "@example.com")
    fake_x_publisher.account = replace(
        fake_x_publisher.account, confirmed_email="outside@example.org"
    )

    refused = await complete(sign_in_browser, await begin(sign_in_browser))

    assert refused.status_code == 403
    assert refused.json()["detail"] == "email_not_allowed"
    still_me = await sign_in_browser.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {old_access}"}
    )
    assert still_me.json()["email"] == original["email"]


async def test_cross_browser_state_cannot_issue_a_session_or_spend_the_original_attempt(
    sign_in_app, sign_in_browser, fake_x_publisher
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    state = await begin(sign_in_browser)
    async with AsyncClient(
        transport=ASGITransport(app=sign_in_app), base_url="http://test"
    ) as stranger:
        response = await complete(stranger, state)
        assert response.status_code == 400
        assert "refresh_token" not in stranger.cookies
    assert fake_x_publisher.exchanges == []
    assert (await complete(sign_in_browser, state)).status_code == 200


@pytest.mark.parametrize("error", ["access_denied", "temporarily_unavailable"])
async def test_provider_cancellation_or_failure_consumes_the_attempt_without_session(
    sign_in_browser, fake_x_publisher, error
):
    state = await begin(sign_in_browser)
    secret = sign_in_browser.cookies["x_sign_in_browser"]
    response = await sign_in_browser.post(
        "/api/v1/login/x/complete", json={"state": state, "error": error}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "x_authorization_cancelled" if error == "access_denied" else "x_authorization_invalid"
    )
    assert fake_x_publisher.exchanges == []
    assert "refresh_token" not in sign_in_browser.cookies
    sign_in_browser.cookies.set("x_sign_in_browser", secret)
    assert (await complete(sign_in_browser, state)).status_code == 400


async def test_missing_confirmed_email_never_starts_a_session(sign_in_browser, fake_x_publisher):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    fake_x_publisher.account = replace(fake_x_publisher.account, confirmed_email=None)
    response = await complete(sign_in_browser, await begin(sign_in_browser))
    assert response.status_code == 400
    assert response.json()["detail"] == "x_email_required"
    assert "refresh_token" not in sign_in_browser.cookies


async def test_missing_permissions_never_starts_a_session(sign_in_browser):
    response = await complete(sign_in_browser, await begin(sign_in_browser))
    assert response.status_code == 400
    assert response.json()["detail"] == "x_permissions_required"
    assert "refresh_token" not in sign_in_browser.cookies


async def test_suspended_x_user_cannot_start_session_or_change_contact(
    sign_in_browser, fake_x_publisher, db
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    first = await complete(sign_in_browser, await begin(sign_in_browser))
    original = await profile(sign_in_browser, first)
    stored = await db.get(User, original["id"])
    stored.suspended_until = datetime.now(timezone.utc) + timedelta(days=1)
    await db.commit()
    sign_in_browser.cookies.clear()
    fake_x_publisher.account = replace(
        fake_x_publisher.account, confirmed_email="changed@example.com"
    )
    refused = await complete(sign_in_browser, await begin(sign_in_browser))
    assert refused.status_code == 401
    assert refused.json()["detail"] == "account_suspended"
    assert "refresh_token" not in sign_in_browser.cookies
    stored.suspended_until = None
    await db.commit()
    still_me = await sign_in_browser.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {first.json()['access_token']}"}
    )
    assert still_me.json()["email"] == original["email"]


async def test_x_session_uses_the_existing_refresh_rotation_and_logout(
    sign_in_browser, fake_x_publisher
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    original = await profile(
        sign_in_browser, await complete(sign_in_browser, await begin(sign_in_browser))
    )
    refreshed = await sign_in_browser.post("/api/v1/refresh-token")
    assert (await profile(sign_in_browser, refreshed))["id"] == original["id"]
    assert (await sign_in_browser.post("/api/v1/logout")).status_code == 200
    assert (await sign_in_browser.post("/api/v1/refresh-token")).status_code == 401


async def test_email_sign_in_cannot_resolve_an_x_identified_user(
    sign_in_browser, fake_x_publisher, new_browser
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    await complete(sign_in_browser, await begin(sign_in_browser))
    response = await new_browser().post(
        "/api/v1/login/magic-link/request", json={"email": "ada@example.com"}
    )
    assert response.status_code == 404


async def test_sign_in_restores_lost_credentials_without_changing_stable_account(
    sign_in_browser, fake_x_publisher, db, new_browser, monkeypatch
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    first = await complete(sign_in_browser, await begin(sign_in_browser))
    original = await profile(sign_in_browser, first)
    await db.execute(delete(XConnection).where(XConnection.user_id == original["id"]))
    await db.commit()
    returned = await complete(sign_in_browser, await begin(sign_in_browser))
    assert (await profile(sign_in_browser, returned))["id"] == original["id"]
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "")
    connected = await new_browser().get(
        "/api/v1/x-connection",
        headers={"Authorization": f"Bearer {returned.json()['access_token']}"},
    )
    assert connected.status_code == 200
    assert connected.json()["handle"] == "ada"
    assert connected.json()["needs_reconnect"] is False


async def test_x_completion_is_mounted_in_the_production_app(new_browser):
    response = await new_browser().post(
        "/api/v1/login/x/complete", json={"state": "state", "code": "code"}
    )
    assert response.status_code == 400
    assert "refresh_token" not in response.cookies


async def test_a_legacy_publishing_connection_cannot_be_taken_over_by_sign_in(
    sign_in_browser, fake_x_publisher, db, legacy_user, fixed_clock
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    legacy_tokens = await fake_x_publisher.exchange_code(
        code="legacy", code_verifier="verifier", now=fixed_clock()
    )
    await save_connection(
        db,
        user_id=legacy_user.id,
        account=fake_x_publisher.account,
        tokens=legacy_tokens,
        now=fixed_clock(),
    )
    await db.commit()
    refused = await complete(sign_in_browser, await begin(sign_in_browser))
    assert refused.status_code == 409
    assert refused.json()["detail"] == "x_account_unavailable"
    assert "refresh_token" not in sign_in_browser.cookies
    await db.execute(delete(XConnection).where(XConnection.user_id == legacy_user.id))
    await db.commit()
    fake_x_publisher.account = replace(fake_x_publisher.account, display_name="After refusal")
    created = await profile(
        sign_in_browser, await complete(sign_in_browser, await begin(sign_in_browser))
    )
    assert created["id"] != legacy_user.id
    assert created["first_name"] == "After refusal"


async def test_an_expired_or_refused_x_code_requires_restarting_authorization(
    sign_in_browser, fake_x_publisher
):
    fake_x_publisher.fail_exchange = XReconnectNeededError("X refused the authorization code")
    response = await complete(sign_in_browser, await begin(sign_in_browser))
    assert response.status_code == 400
    assert response.json()["detail"] == "x_authorization_invalid"
    assert "refresh_token" not in sign_in_browser.cookies
