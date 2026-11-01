"""The official MCP SDK client signs in to Pumpkit and calls its tools, as a real app would."""

import time
from datetime import timedelta
from typing import Optional

import httpx2
import pytest
from httpx import AsyncClient
from mcp import Client
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)

from pumpkit.main import app
from tests.oauth_app import ISSUER, MCP_URL, REDIRECT, query

pytestmark = pytest.mark.usefixtures("subscribed")

DOCUMENT_URL = "https://sdk.example.com/oauth/client.json"


class InMemoryTokenStorage:
    def __init__(self) -> None:
        self.tokens: list[OAuthToken] = []
        self.client_info: Optional[OAuthClientInformationFull] = None

    async def get_tokens(self) -> Optional[OAuthToken]:
        return self.tokens[-1] if self.tokens else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens.append(tokens)

    async def get_client_info(self) -> Optional[OAuthClientInformationFull]:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


class SignedInUser:
    """The User's browser: it opens the authorization URL and clicks Allow on the consent page."""

    def __init__(self, browser: AsyncClient) -> None:
        self.browser = browser
        self.authorizations = 0
        self._redirect_url = ""

    async def open(self, authorization_url: str) -> None:
        self.authorizations += 1
        assert authorization_url.startswith(f"{ISSUER}/api/v1/oauth/authorize?")
        started = await self.browser.get(authorization_url.removeprefix(ISSUER))
        assert started.status_code == 303, started.text
        request_id = query(started.headers["location"])["request"]
        approved = await self.browser.post(f"/api/v1/oauth/authorizations/{request_id}/approve")
        assert approved.status_code == 200, approved.text
        self._redirect_url = approved.json()["redirect_url"]

    async def callback(self) -> AuthorizationCodeResult:
        params = query(self._redirect_url)
        return AuthorizationCodeResult(
            code=params["code"], state=params["state"], iss=params["iss"]
        )


@pytest.fixture
def storage() -> InMemoryTokenStorage:
    return InMemoryTokenStorage()


@pytest.fixture
def signed_in_user(new_browser, authed_client) -> SignedInUser:
    # `new_browser` points the app at the test database; the SDK's client needs nothing else.
    return SignedInUser(authed_client)


def sdk_client(
    storage: InMemoryTokenStorage, user: SignedInUser, client_metadata_url: Optional[str] = None
) -> Client:
    provider = OAuthClientProvider(
        server_url=MCP_URL,
        client_metadata=OAuthClientMetadata(
            client_name="SDK test",
            redirect_uris=[REDIRECT],  # pyright: ignore[reportArgumentType]
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
        ),
        storage=storage,
        redirect_handler=user.open,
        callback_handler=user.callback,
        client_metadata_url=client_metadata_url,
    )
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url=ISSUER, auth=provider
    )
    return Client(streamable_http_client(MCP_URL, http_client=http))


async def test_the_sdk_client_registers_signs_in_and_calls_a_tool(storage, signed_in_user):
    async with sdk_client(storage, signed_in_user) as client:
        tools = await client.list_tools()
        result = await client.call_tool("list_inspiration_authors", {})

    assert "get_usage" in {tool.name for tool in tools.tools}
    assert result.is_error is False
    assert result.structured_content == {"data": []}
    assert storage.client_info is not None
    assert storage.client_info.client_id.startswith("oauth_client_")
    assert signed_in_user.authorizations == 1
    assert [token.scope for token in storage.tokens] == ["pumpkit"]


async def test_the_sdk_client_identifies_itself_by_its_metadata_document(
    storage, signed_in_user, authed_client, fake_client_metadata_fetcher
):
    fake_client_metadata_fetcher.serve(
        {
            "client_id": DOCUMENT_URL,
            "client_name": "SDK test",
            "redirect_uris": [REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_method": "none",
        }
    )

    async with sdk_client(storage, signed_in_user, client_metadata_url=DOCUMENT_URL) as client:
        result = await client.call_tool("list_inspiration_authors", {})

    assert result.is_error is False
    assert storage.client_info is not None
    assert storage.client_info.client_id == DOCUMENT_URL
    assert fake_client_metadata_fetcher.fetched == [DOCUMENT_URL]
    connections = (await authed_client.get("/api/v1/app-connections")).json()["data"]
    assert [(c["app_name"], c["verified_domain"]) for c in connections] == [
        ("SDK test", "sdk.example.com")
    ]


async def test_the_sdk_client_refreshes_an_expired_token_without_signing_in_again(
    storage, signed_in_user, clock, monkeypatch
):
    async with sdk_client(storage, signed_in_user) as client:
        await client.list_tools()
        # Past the access token's hour on both the app's clock and Pumpkit's.
        later = time.time() + timedelta(hours=1, minutes=5).total_seconds()
        # The SDK reads `time.time` to decide a token has expired.
        monkeypatch.setattr(time, "time", lambda: later)
        clock.advance(timedelta(hours=1, minutes=5))
        result = await client.call_tool("list_inspiration_authors", {})

    assert result.is_error is False
    assert signed_in_user.authorizations == 1
    assert len(storage.tokens) == 2
    assert storage.tokens[1].refresh_token != storage.tokens[0].refresh_token
