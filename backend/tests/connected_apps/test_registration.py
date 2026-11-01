from datetime import timedelta

import pytest
from sqlalchemy import select

from pumpkit.connected_apps.models import AppConnection, OAuthAuthorization, OAuthClient
from pumpkit.core.security import hash_token

REGISTER = "/api/v1/oauth/register"
REDIRECT = "http://127.0.0.1:33418/callback"


@pytest.fixture
def browser(new_browser):
    return new_browser()


async def test_a_public_client_registers_without_a_secret(browser, fixed_clock):
    response = await browser.post(
        REGISTER,
        json={
            "redirect_uris": [REDIRECT],
            "client_name": "  Gemini CLI  ",
            "token_endpoint_auth_method": "none",
            "client_uri": "https://example.com",
            "software_id": "gemini",
            "software_version": "1.2.3",
            "scope": "ignored",
            "something_else": 1,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body.pop("client_id").startswith("oauth_client_")
    assert body == {
        "client_id_issued_at": int(fixed_clock().timestamp()),
        "redirect_uris": [REDIRECT],
        "client_name": "Gemini CLI",
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_uri": "https://example.com",
        "software_id": "gemini",
        "software_version": "1.2.3",
    }
    assert response.headers["cache-control"] == "no-store"


async def test_a_client_that_names_no_auth_method_gets_a_basic_secret(browser, db):
    response = await browser.post(REGISTER, json={"redirect_uris": [REDIRECT]})

    body = response.json()
    assert response.status_code == 201
    assert body["token_endpoint_auth_method"] == "client_secret_basic"
    assert body["client_name"] == "Unnamed app"
    assert body["client_secret"].startswith("pumpkit_cs_")
    assert body["client_secret_expires_at"] == 0
    stored = await db.get(OAuthClient, body["client_id"])
    assert stored is not None
    assert stored.kind == "registered"
    assert stored.client_secret_hash == hash_token(body["client_secret"])


@pytest.mark.parametrize("method", ["client_secret_post", "client_secret_basic"])
async def test_secret_methods_are_honoured(browser, method):
    response = await browser.post(
        REGISTER, json={"redirect_uris": [REDIRECT], "token_endpoint_auth_method": method}
    )

    assert response.status_code == 201
    assert response.json()["token_endpoint_auth_method"] == method
    assert "client_secret" in response.json()


async def test_a_public_client_is_stored_without_a_secret_hash(browser, db):
    response = await browser.post(
        REGISTER, json={"redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none"}
    )

    stored = await db.get(OAuthClient, response.json()["client_id"])
    assert stored is not None
    assert stored.client_secret_hash is None
    assert stored.redirect_uris == [REDIRECT]


async def test_the_name_loses_control_characters(browser):
    response = await browser.post(
        REGISTER, json={"redirect_uris": [REDIRECT], "client_name": "My\x00 App\n"}
    )

    assert response.json()["client_name"] == "My App"


async def test_the_name_loses_characters_that_could_disguise_it(browser):
    response = await browser.post(
        REGISTER,
        json={"redirect_uris": [REDIRECT], "client_name": "Pay\u202epal\u200b \u2066App\ufeff"},
    )

    assert response.json()["client_name"] == "Paypal App"


@pytest.mark.parametrize(
    "redirect_uris",
    [
        None,
        [],
        "http://localhost/cb",
        [f"https://example.com/{i}" for i in range(11)],
        ["javascript:alert(1)"],
        ["https://example.com/cb", "http://example.com/cb"],
        ["https://example.com/cb#frag"],
        [5],
        ["https://example.com/cb?code=1"],
        ["http://127.0.0.1/cb?team=1&state=x"],
        ["cursor://app/cb?iss"],
        ["https://example.com/cb?error="],
        ["https://example.com/cb?error_description=x"],
    ],
)
async def test_bad_redirect_uris_are_invalid_redirect_uri(browser, redirect_uris):
    body = {} if redirect_uris is None else {"redirect_uris": redirect_uris}

    response = await browser.post(REGISTER, json=body)

    assert response.status_code == 400
    assert response.json().keys() == {"error", "error_description"}
    assert response.json()["error"] == "invalid_redirect_uri"


async def test_ten_redirect_uris_are_accepted(browser):
    uris = [f"https://example.com/{i}" for i in range(10)]

    response = await browser.post(REGISTER, json={"redirect_uris": uris})

    assert response.status_code == 201


@pytest.mark.parametrize(
    "metadata",
    [
        {"token_endpoint_auth_method": "private_key_jwt"},
        {"client_name": "x" * 101},
        {"client_uri": "http://example.com"},
        {"grant_types": ["refresh_token"]},
        {"grant_types": ["authorization_code", "implicit"]},
        {"grant_types": ["authorization_code", "client_credentials"]},
        {"response_types": ["token"]},
        {"software_id": "x" * 201},
        {"software_version": "x" * 201},
    ],
)
async def test_bad_metadata_is_invalid_client_metadata(browser, metadata):
    response = await browser.post(REGISTER, json={"redirect_uris": [REDIRECT], **metadata})

    assert response.status_code == 400
    assert response.json().keys() == {"error", "error_description"}
    assert response.json()["error"] == "invalid_client_metadata"


@pytest.mark.parametrize("body", [b"not json", b"[]", b'"text"'])
async def test_a_body_that_is_not_a_json_object_is_invalid_client_metadata(browser, body):
    response = await browser.post(
        REGISTER, content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


async def test_a_body_over_16_kb_is_refused(browser, db):
    padding = "x" * (16 * 1024)

    response = await browser.post(
        REGISTER, json={"redirect_uris": [REDIRECT], "software_id": padding}
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"
    assert (await db.scalars(select(OAuthClient))).first() is None


async def test_a_streamed_body_over_16_kb_is_refused(browser, db):
    async def chunks():
        for _ in range(40):
            yield b" " * 1024

    response = await browser.post(
        REGISTER, content=chunks(), headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


async def test_json_too_deep_to_parse_is_invalid_client_metadata(browser, monkeypatch):
    class TooDeep:
        @staticmethod
        def loads(_raw):
            raise RecursionError

    # The interpreter's recursion limit varies by version, so force the failure.
    monkeypatch.setattr("pumpkit.connected_apps.mediator.json", TooDeep)

    response = await browser.post(
        REGISTER, content=b"[[[]]]", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


@pytest.mark.parametrize(
    "metadata",
    [{"logo_uri": "http://example.com/l.png"}, {"logo_uri": "https://example.com/" + "x" * 2100}],
)
async def test_a_bad_logo_uri_is_invalid_client_metadata(browser, metadata):
    response = await browser.post(REGISTER, json={"redirect_uris": [REDIRECT], **metadata})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"


async def test_a_long_client_uri_is_invalid_client_metadata(browser):
    response = await browser.post(
        REGISTER,
        json={"redirect_uris": [REDIRECT], "client_uri": "https://example.com/" + "x" * 2100},
    )

    assert response.status_code == 400


async def test_a_https_logo_uri_is_stored(browser):
    response = await browser.post(
        REGISTER, json={"redirect_uris": [REDIRECT], "logo_uri": "https://example.com/l.png"}
    )

    assert response.json()["logo_uri"] == "https://example.com/l.png"


@pytest.mark.parametrize(
    ("metadata", "description"),
    [
        ({"grant_types": ["refresh_token"]}, "grant_types must include authorization_code"),
        ({"client_uri": "http://example.com"}, "client_uri: must be an https URL"),
        ({"client_name": "x" * 101}, "client_name: String should have at most 100 characters"),
        ({"redirect_uris": ["http://example.com/cb"]}, "redirect_uris.0: An http redirect URI"),
    ],
)
async def test_error_descriptions_are_readable(browser, metadata, description):
    body = {"redirect_uris": [REDIRECT], **metadata}

    response = await browser.post(REGISTER, json=body)

    assert response.json()["error_description"].startswith(description)


async def test_the_sixty_first_registration_in_an_hour_is_rate_limited(browser):
    for _ in range(60):
        assert (await browser.post(REGISTER, json={"redirect_uris": [REDIRECT]})).status_code == 201

    response = await browser.post(REGISTER, json={"redirect_uris": [REDIRECT]})

    assert response.status_code == 429
    body = response.json()
    assert body.keys() == {"error", "error_description"}
    assert body["error"] == "temporarily_unavailable"
    assert int(response.headers["retry-after"]) > 0


async def _add_client(db, now, *, age: timedelta, name: str) -> OAuthClient:
    client = OAuthClient(
        kind="registered",
        name=name,
        redirect_uris=[REDIRECT],
        token_endpoint_auth_method="none",
        created_at=now - age,
    )
    db.add(client)
    await db.commit()
    return client


async def _names(db) -> set[str]:
    return {c.name for c in await db.scalars(select(OAuthClient))}


async def test_registering_purges_unused_clients_older_than_30_days(browser, db, fixed_clock):
    await _add_client(db, fixed_clock(), age=timedelta(days=31), name="stale")
    await _add_client(db, fixed_clock(), age=timedelta(days=29), name="recent")

    await browser.post(REGISTER, json={"redirect_uris": [REDIRECT], "client_name": "new"})

    assert await _names(db) == {"recent", "new"}


async def test_the_purge_keeps_an_old_client_that_has_a_connection(browser, db, user, fixed_clock):
    now = fixed_clock()
    connected = await _add_client(db, now, age=timedelta(days=60), name="connected")
    db.add(
        AppConnection(
            user_id=user.id,
            client_id=connected.id,
            scope="pumpkit",
            resource="http://localhost:5173/api/v1/mcp",
            created_at=now - timedelta(days=60),
            revoked_at=now - timedelta(days=50),
        )
    )
    await db.commit()

    await browser.post(REGISTER, json={"redirect_uris": [REDIRECT], "client_name": "new"})

    assert "connected" in await _names(db)


async def test_the_purge_keeps_an_old_client_with_a_recent_authorization(browser, db, fixed_clock):
    now = fixed_clock()
    pending = await _add_client(db, now, age=timedelta(days=60), name="pending")
    db.add(
        OAuthAuthorization(
            id="authorization-1",
            client_id=pending.id,
            redirect_uri=REDIRECT,
            redirect_uri_was_sent=True,
            code_challenge="challenge",
            scope="pumpkit",
            resource="http://localhost:5173/api/v1/mcp",
            created_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=2) + timedelta(minutes=30),
        )
    )
    await db.commit()

    await browser.post(REGISTER, json={"redirect_uris": [REDIRECT], "client_name": "new"})

    assert "pending" in await _names(db)


async def test_the_purge_removes_an_old_client_whose_only_authorization_is_over_30_days_old(
    browser, db, fixed_clock
):
    now = fixed_clock()
    old = await _add_client(db, now, age=timedelta(days=90), name="abandoned")
    db.add(
        OAuthAuthorization(
            id="authorization-old",
            client_id=old.id,
            redirect_uri=REDIRECT,
            redirect_uri_was_sent=True,
            code_challenge="challenge",
            scope="pumpkit",
            resource="http://localhost:5173/api/v1/mcp",
            created_at=now - timedelta(days=45),
            expires_at=now - timedelta(days=45) + timedelta(minutes=30),
        )
    )
    await db.commit()

    await browser.post(REGISTER, json={"redirect_uris": [REDIRECT], "client_name": "new"})

    assert "abandoned" not in await _names(db)
