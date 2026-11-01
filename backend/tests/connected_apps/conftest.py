from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from pumpkit.core.db.base import Base

REDIRECT = "http://127.0.0.1:33418/callback"
# The PKCE pair of RFC 7636's appendix B.
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
MCP_URL = "http://localhost:5173/api/v1/mcp"
ISSUER = "http://localhost:5173"
CONSENT = "http://localhost:5173/oauth/consent"
AUTHORIZE = "/api/v1/oauth/authorize"
TOKEN = "/api/v1/oauth/token"
REVOKE = "/api/v1/oauth/revoke"


def query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


async def register(browser: AsyncClient, *redirect_uris: str, **metadata: str) -> str:
    """The id of a new public app registered with these redirect URIs."""
    response = await browser.post(
        "/api/v1/oauth/register",
        json={
            "redirect_uris": list(redirect_uris),
            "token_endpoint_auth_method": "none",
            **metadata,
        },
    )
    return response.json()["client_id"]


async def start_for(browser: AsyncClient, client_id: str, **params: str) -> Response:
    """Authorize a valid PKCE request from the app, leaving out the redirect URI unless given."""
    return await browser.get(
        AUTHORIZE,
        params={
            "client_id": client_id,
            "response_type": "code",
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
            **params,
        },
    )


async def approved_code(
    user_browser: AsyncClient,
    app: AsyncClient,
    client_id: str,
    *,
    send_redirect_uri: bool = True,
    **params,
) -> str:
    """
    The code the app receives once the signed-in `user_browser` allows its authorization, which
    sends `REDIRECT` unless told otherwise or `send_redirect_uri` is False. Approving needs
    access: request `subscribed` or `sells_no_plans` first.
    """
    if send_redirect_uri:
        params = {"redirect_uri": REDIRECT, **params}
    started = await start_for(app, client_id, **params)
    request_id = query(started.headers["location"])["request"]
    approved = await user_browser.post(f"/api/v1/oauth/authorizations/{request_id}/approve")
    assert approved.status_code == 200, approved.text
    return query(approved.json()["redirect_url"])["code"]


async def exchange(app: AsyncClient, client_id: str, code: str, **fields: str) -> Response:
    """Redeem the code as a public app that sent `REDIRECT` at authorize."""
    return await app.post(
        TOKEN,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT,
            "code_verifier": VERIFIER,
            **fields,
        },
    )


async def refresh(app: AsyncClient, client_id: str, refresh_token: str, **fields: str) -> Response:
    return await app.post(
        TOKEN,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
            **fields,
        },
    )


@pytest_asyncio.fixture
async def oauth_client(new_browser) -> str:
    """The id of a public app registered through Dynamic Client Registration."""
    return await register(new_browser(), REDIRECT, client_name="Gemini CLI")


@pytest.fixture
def authorize_params(oauth_client) -> dict[str, str]:
    """A valid authorize request from `oauth_client`; tests override or drop fields."""
    return {
        "client_id": oauth_client,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": "xyz",
    }


@pytest_asyncio.fixture
async def foreign_keys_session(tmp_path):
    """A session on its own database with SQLite's foreign keys on, as Postgres enforces them."""
    # The shared test engine leaves them off.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fk.db'}", poolclass=NullPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys_on(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()
