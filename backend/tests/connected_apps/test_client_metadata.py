"""Apps that identify themselves by a Client ID Metadata Document URL (CIMD)."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.connected_apps.service import client_metadata
from pumpkit.connected_apps.service.client_metadata import (
    FakeClientMetadataFetcher,
    FetchedClientMetadata,
)
from tests.oauth_app import CONSENT, REDIRECT, approved_code, exchange, query, start_for

DOCUMENT_URL = "https://app.example.com/oauth/client.json"
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def document(**fields) -> dict:
    return {
        "client_id": DOCUMENT_URL,
        "client_name": "Example",
        "redirect_uris": [REDIRECT],
        "token_endpoint_auth_method": "none",
        **fields,
    }


@pytest.fixture
def browser(new_browser):
    return new_browser()


def details(location: str) -> str:
    return f"/api/v1/oauth/authorizations/{query(location)['request']}"


async def test_an_app_with_a_valid_document_reaches_the_consent_page_verified(
    browser, authed_client, fake_client_metadata_fetcher
):
    fake_client_metadata_fetcher.serve(document())

    started = await start_for(browser, DOCUMENT_URL, redirect_uri=REDIRECT)

    assert started.status_code == 303
    assert started.headers["location"].startswith(f"{CONSENT}?request=")
    body = (await authed_client.get(details(started.headers["location"]))).json()
    assert body["client"] == {
        "name": "Example",
        "verified_domain": "app.example.com",
        "redirect_host": None,
        "is_local": True,
    }


async def test_the_document_is_cached_and_fetched_again_after_24_hours(
    browser, clock, fake_client_metadata_fetcher
):
    fake_client_metadata_fetcher.serve(document())

    await start_for(browser, DOCUMENT_URL)
    clock.advance(timedelta(hours=23))
    await start_for(browser, DOCUMENT_URL)
    clock.advance(timedelta(hours=2))
    await start_for(browser, DOCUMENT_URL)

    assert fake_client_metadata_fetcher.fetched == [DOCUMENT_URL, DOCUMENT_URL]


@pytest.mark.parametrize(
    ("max_age", "refetch_after"),
    [
        (600, timedelta(minutes=10)),
        (0, timedelta(minutes=5)),
        (10**9, timedelta(hours=24)),
        (10**15, timedelta(hours=24)),
    ],
)
async def test_max_age_sets_freshness_between_five_minutes_and_a_day(
    browser, clock, fake_client_metadata_fetcher, max_age, refetch_after
):
    fake_client_metadata_fetcher.serve(document(), max_age_seconds=max_age)

    await start_for(browser, DOCUMENT_URL)
    clock.advance(refetch_after - timedelta(seconds=1))
    await start_for(browser, DOCUMENT_URL)
    assert len(fake_client_metadata_fetcher.fetched) == 1
    clock.advance(timedelta(seconds=2))
    await start_for(browser, DOCUMENT_URL)
    assert len(fake_client_metadata_fetcher.fetched) == 2


async def test_a_refetched_document_replaces_the_cached_one(
    browser, authed_client, clock, fake_client_metadata_fetcher
):
    fake_client_metadata_fetcher.serve(document())
    await start_for(browser, DOCUMENT_URL)
    fake_client_metadata_fetcher.serve(document(client_name="Example 2"))
    clock.advance(timedelta(hours=25))

    started = await start_for(browser, DOCUMENT_URL)

    body = (await authed_client.get(details(started.headers["location"]))).json()
    assert body["client"]["name"] == "Example 2"


async def test_the_stale_copy_is_used_when_a_refetch_fails(
    browser, authed_client, clock, fake_client_metadata_fetcher
):
    fake_client_metadata_fetcher.serve(document())
    await start_for(browser, DOCUMENT_URL)
    fake_client_metadata_fetcher.documents.clear()
    clock.advance(timedelta(days=30))

    started = await start_for(browser, DOCUMENT_URL)

    assert fake_client_metadata_fetcher.fetched == [DOCUMENT_URL, DOCUMENT_URL]
    assert started.headers["location"].startswith(f"{CONSENT}?request=")
    body = (await authed_client.get(details(started.headers["location"]))).json()
    assert body["client"]["verified_domain"] == "app.example.com"


async def test_an_unreachable_document_with_nothing_cached_is_an_unknown_app(browser):
    started = await start_for(browser, DOCUMENT_URL)

    assert started.headers["location"] == f"{CONSENT}?error=invalid_client"


@pytest.mark.parametrize(
    "fields",
    [
        {"client_id": "https://app.example.com/oauth/other.json"},
        {"redirect_uris": None},
        {"redirect_uris": []},
        {"redirect_uris": ["http://example.com/cb"]},
        {"token_endpoint_auth_method": "client_secret_basic"},
        {"token_endpoint_auth_method": "client_secret_post"},
        {"token_endpoint_auth_method": "tls_client_auth"},
    ],
    ids=[
        "mismatched-client-id",
        "no-redirect-uris",
        "empty-redirect-uris",
        "http-redirect-uri",
        "client-secret-basic",
        "client-secret-post",
        "tls-client-auth",
    ],
)
async def test_an_invalid_document_is_refused(browser, fake_client_metadata_fetcher, fields):
    served = {key: value for key, value in document(**fields).items() if value is not None}
    fake_client_metadata_fetcher.documents[DOCUMENT_URL] = FetchedClientMetadata(served)

    started = await start_for(browser, DOCUMENT_URL)

    assert started.headers["location"] == f"{CONSENT}?error=invalid_client"


async def test_a_document_that_is_not_an_object_is_refused(browser, fake_client_metadata_fetcher):
    fake_client_metadata_fetcher.documents[DOCUMENT_URL] = FetchedClientMetadata([DOCUMENT_URL])

    started = await start_for(browser, DOCUMENT_URL)

    assert started.headers["location"] == f"{CONSENT}?error=invalid_client"


async def test_the_redirect_uri_must_be_one_the_document_lists(
    browser, fake_client_metadata_fetcher
):
    fake_client_metadata_fetcher.serve(document())

    started = await start_for(browser, DOCUMENT_URL, redirect_uri="http://127.0.0.1:1/other")

    assert started.headers["location"] == f"{CONSENT}?error=invalid_redirect_uri"


async def test_an_app_without_a_name_is_named_after_its_host(
    browser, authed_client, fake_client_metadata_fetcher
):
    fake_client_metadata_fetcher.serve({"client_id": DOCUMENT_URL, "redirect_uris": [REDIRECT]})

    started = await start_for(browser, DOCUMENT_URL)

    body = (await authed_client.get(details(started.headers["location"]))).json()
    assert body["client"]["name"] == "app.example.com"


@pytest.mark.parametrize(
    "client_id",
    [
        "https://app.example.com",
        "https://app.example.com/",
        "http://app.example.com/oauth/client.json",
    ],
)
async def test_a_url_without_a_path_or_https_is_not_a_document(
    browser, fake_client_metadata_fetcher, client_id
):
    fake_client_metadata_fetcher.serve(document(client_id=client_id))

    started = await start_for(browser, client_id)

    assert started.headers["location"] == f"{CONSENT}?error=invalid_client"
    assert fake_client_metadata_fetcher.fetched == []


async def test_the_app_is_public_and_its_private_key_jwt_is_ignored(
    browser, authed_client, subscribed, fake_client_metadata_fetcher
):
    fake_client_metadata_fetcher.serve(
        document(
            token_endpoint_auth_method="private_key_jwt",
            jwks_uri="https://app.example.com/oauth/jwks.json",
        )
    )

    code = await approved_code(authed_client, browser, DOCUMENT_URL)
    response = await exchange(browser, DOCUMENT_URL, code)

    assert response.status_code == 200, response.text
    assert response.json()["token_type"] == "Bearer"


BUNDLED = json.loads(
    (Path(client_metadata.__file__).with_name("known_client_documents.json")).read_text()
)
BIG_CLIENTS = {
    "https://claude.ai/oauth/mcp-oauth-client-metadata": (
        "Claude",
        "https://claude.ai/api/mcp/auth_callback",
    ),
    "https://claude.ai/oauth/claude-code-client-metadata": (
        "Claude Code",
        "http://localhost:51234/callback",
    ),
    "https://chatgpt.com/oauth/client.json": (
        "ChatGPT",
        "https://chatgpt.com/connector_platform_oauth_redirect",
    ),
    "https://chatgpt.com/oauth/codex/client.json": ("Codex", "http://127.0.0.1:1455/callback"),
    "https://vscode.dev/oauth/client-metadata.json": (
        "Visual Studio Code",
        "http://127.0.0.1:33418/",
    ),
}


@pytest.mark.parametrize("url", list(BIG_CLIENTS))
async def test_the_bundled_copy_is_used_when_the_live_fetch_fails_and_nothing_is_cached(
    browser, authed_client, fake_client_metadata_fetcher, url
):
    name, redirect_uri = BIG_CLIENTS[url]

    started = await start_for(browser, url, redirect_uri=redirect_uri)

    assert fake_client_metadata_fetcher.fetched == [url]
    assert started.headers["location"].startswith(f"{CONSENT}?request=")
    body = (await authed_client.get(details(started.headers["location"]))).json()
    assert body["client"]["name"] == name
    assert body["client"]["verified_domain"] == urlsplit(url).hostname


@pytest.mark.parametrize("url", list(BIG_CLIENTS))
async def test_a_live_document_wins_over_the_bundled_copy(
    browser, authed_client, fake_client_metadata_fetcher, url
):
    live = {
        **BUNDLED[url]["document"],
        "client_name": "Renamed",
        "redirect_uris": ["https://moved.example.com/callback"],
    }
    fake_client_metadata_fetcher.serve(live)
    _, old_redirect_uri = BIG_CLIENTS[url]

    old = await start_for(browser, url, redirect_uri=old_redirect_uri)
    started = await start_for(browser, url, redirect_uri="https://moved.example.com/callback")

    assert old.headers["location"] == f"{CONSENT}?error=invalid_redirect_uri"
    body = (await authed_client.get(details(started.headers["location"]))).json()
    assert body["client"]["name"] == "Renamed"


async def test_a_bundled_copy_gives_way_to_the_live_document_on_the_next_authorization(
    browser, authed_client, fake_client_metadata_fetcher
):
    url = "https://claude.ai/oauth/mcp-oauth-client-metadata"
    await start_for(browser, url)
    fake_client_metadata_fetcher.serve({**BUNDLED[url]["document"], "client_name": "Claude 2"})

    started = await start_for(browser, url)

    assert fake_client_metadata_fetcher.fetched == [url, url]
    body = (await authed_client.get(details(started.headers["location"]))).json()
    assert body["client"]["name"] == "Claude 2"


@dataclass
class racing_fetcher(FakeClientMetadataFetcher):
    """Serves the document after another authorization has stored the same app first."""

    engine: Any = None

    async def fetch(self, url: str) -> FetchedClientMetadata:
        async with AsyncSession(self.engine) as other:
            await client_metadata.resolve_metadata_document_client(
                other, url, FakeClientMetadataFetcher(self.documents), now=NOW
            )
            await other.commit()
        return await super().fetch(url)


async def test_two_first_authorizations_of_one_app_both_resolve_it(foreign_keys_session):
    fetcher = racing_fetcher(engine=foreign_keys_session.bind)
    fetcher.serve(document())

    client = await client_metadata.resolve_metadata_document_client(
        foreign_keys_session, DOCUMENT_URL, fetcher, now=NOW
    )

    assert client is not None
    assert client.name == "Example"
