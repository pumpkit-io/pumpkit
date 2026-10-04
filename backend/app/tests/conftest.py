"""Shared pytest configuration for backend tests.

`app.core.config.settings` is instantiated at import time, so a deterministic
test environment is injected into `os.environ` *before* any `app.*` import.
Real env vars win (setdefault), which lets CI override individual values.
"""

import os

_TEST_ENV = {
    "ENV": "local",
    "APP_NAME": "TestApp",
    "BACKEND_URL": "http://localhost:8000",
    "BACKEND_PORT": "8000",
    "FRONTEND_URL": "http://localhost:5173",
    "FRONTEND_PORT": "5173",
    "CORS_ORIGINS": '["http://localhost:5173"]',
    "POSTGRES_USER": "postgres",
    "POSTGRES_PASSWORD": "postgres",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "postgres",
    "JWT_SECRET_KEY": "test-secret-key-test-secret-key-0123456789",
    "JWT_ALGORITHM": "HS256",
    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": "30",
    "JWT_REFRESH_TOKEN_EXPIRE_DAYS": "30",
    "JWT_ISSUER": "testapp",
    "JWT_AUDIENCE": "testapp-api",
    "COOKIE_MAX_AGE_SECONDS": "2592000",
    "FERNET_ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    "MAGIC_LINK_TOKEN_DURATION_MINUTES": "15",
    "MAGIC_LINK_TOKEN_NUM_BYTES": "32",
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
    "GOOGLE_OAUTH_REDIRECT_URI": "http://localhost:8000/api/v1/oauth/google/callback",
    "GOOGLE_NONCE_TOKEN_NUM_BYTES": "64",
    "GOOGLE_CODE_VERIFIER_TOKEN_NUM_BYTES": "64",
    "GOOGLE_COOKIE_MAX_AGE_SECONDS": "600",
    "GOOGLE_TOKEN_ENDPOINT_TIMEOUT_SECONDS": "30",
    "RESEND_API_KEY": "re_test",
    "RESEND_NOREPLY_ADDRESS": "noreply@example.com",
    "RESEND_SUPPORT_ADDRESS": "support@example.com",
    "STRIPE_SECRET_KEY": "sk_test_dummy",
    "STRIPE_PUBLISHABLE_KEY": "pk_test_dummy",
    "STRIPE_WEBHOOK_SECRET": "whsec_dummy",
    "STRIPE_CHECKOUT_SUCCESS_URL": "http://localhost:5173/billing/success",
    "STRIPE_CHECKOUT_CANCEL_URL": "http://localhost:5173/billing/cancelled",
    "STRIPE_BILLING_PORTAL_RETURN_URL": "http://localhost:5173/billing",
    "BILLING_PLAN_KEYS": '["pumpkit_pro_monthly"]',
    "OPENROUTER_API_KEY": "sk-or-test",
    "POSTHOG_ENABLED": "false",
}
for _key, _value in _TEST_ENV.items():
    os.environ.setdefault(_key, _value)

import re  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from typing import Awaitable, Callable, Iterator, Optional  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402
from urllib.parse import parse_qs, urlsplit  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import Depends  # noqa: E402
from httpx import ASGITransport, AsyncClient, Response  # noqa: E402
from sqlalchemy import event, select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

import app.core.exceptions as exceptions_module  # noqa: E402
from app.api.dependencies import get_current_user  # noqa: E402
from app.core.auth_mailer import OutboxAuthMailer, get_auth_mailer  # noqa: E402
from app.core.billing_gateway import FakeBillingGateway, get_billing_gateway  # noqa: E402
from app.core.clock import get_clock  # noqa: E402
from app.core.google_sign_in import (  # noqa: E402
    FakeGoogleSignIn,
    GoogleClaims,
    get_google_sign_in,
)
from app.core.rate_limit import limiter  # noqa: E402
from app.db import models  # noqa: E402,F401  (registers every table on Base.metadata)
from app.db.base import Base  # noqa: E402
from app.db.models import MagicLink, User  # noqa: E402
from app.db.session import get_async_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def auth_outbox():
    """
    Every test sends auth email to an in-memory outbox instead of Resend.
    Request it by name to read `auth_outbox.messages` or set `auth_outbox.fail = True`.
    """
    outbox = OutboxAuthMailer()
    app.dependency_overrides[get_auth_mailer] = lambda: outbox
    yield outbox
    app.dependency_overrides.pop(get_auth_mailer, None)


class FrozenClock:
    """A clock that stands still until a test moves it."""

    def __init__(self, now: datetime) -> None:
        self._now = now

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


@pytest.fixture
def clock() -> Iterator[FrozenClock]:
    """
    Freeze the time endpoints read through `get_clock` (Magic link cool-down and
    expiry) at the real current time. Move it with `clock.advance(timedelta(...))`.
    """
    frozen = FrozenClock(datetime.now(timezone.utc))
    app.dependency_overrides[get_clock] = lambda: frozen
    yield frozen
    app.dependency_overrides.pop(get_clock, None)


@pytest.fixture(autouse=True)
def fake_google():
    """
    Every test exchanges Google authorization codes with a fake instead of Google.
    Request it by name to set `fake_google.claims` or `fake_google.fail = True`.
    """
    fake = FakeGoogleSignIn()
    app.dependency_overrides[get_google_sign_in] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_google_sign_in, None)


@pytest.fixture(autouse=True)
def fake_billing():
    """
    Every test bills through a fake `BillingGateway` instead of Stripe. Request it
    by name to configure results, read its recorded calls, set `fail_on`, or sign
    webhook events with `fake_billing.signed_event(...)`.
    """
    fake = FakeBillingGateway()
    app.dependency_overrides[get_billing_gateway] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_billing_gateway, None)


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """The slowapi limiter is a process-wide in-memory store; start each test with empty counters."""
    limiter.reset()
    yield


@pytest_asyncio.fixture
async def db_engine(tmp_path):
    # A per-test SQLite *file* (not :memory:) with one connection per session:
    # the test's `db` session and the request sessions opened by `client` then
    # run independent transactions, like separate Postgres connections would.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", poolclass=NullPool)

    # SQLite's driver manages transactions itself, which breaks SAVEPOINT
    # rollback semantics (stripe_events.try_record_event relies on them).
    # SQLAlchemy's documented fix: disable driver-level transactions and emit
    # BEGIN ourselves. WAL lets one session write while another holds a read.
    @event.listens_for(engine.sync_engine, "connect")
    def _configure_connection(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    @event.listens_for(engine.sync_engine, "begin")
    def _emit_begin(conn):
        conn.exec_driver_sql("BEGIN")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_maker(db_engine):
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(db_session_maker):
    async with db_session_maker() as session:
        yield session


@pytest_asyncio.fixture
async def user(db) -> User:
    u = User(email="alice@example.com", display_name="Alice")
    db.add(u)
    await db.commit()
    await db.refresh(u)
    # End the read transaction opened by refresh(): SQLite (WAL) pins a snapshot
    # for its lifetime, so later `db.refresh(...)` calls in tests would otherwise
    # not see commits made by the request sessions.
    await db.commit()
    return u


@pytest_asyncio.fixture
async def client(db_session_maker, user):
    async def _get_db():
        async with db_session_maker() as session:
            yield session

    # Load the user through the request's own session so handlers that mutate
    # `current_user` and commit actually persist the change.
    async def _get_user(db: AsyncSession = Depends(get_async_db)) -> User:
        db_user = await db.get(User, user.id)
        assert db_user is not None
        return db_user

    app.dependency_overrides[get_async_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def new_browser(db_session_maker):
    """
    Factory for ASGI clients that each act as one browser with its own cookie jar.
    Only the database is overridden: real access-token verification runs.
    """

    async def _get_db():
        async with db_session_maker() as session:
            yield session

    app.dependency_overrides[get_async_db] = _get_db
    browsers: list[AsyncClient] = []

    def _new() -> AsyncClient:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        browser = AsyncClient(transport=transport, base_url="http://test")
        browsers.append(browser)
        return browser

    yield _new
    for browser in browsers:
        await browser.aclose()
    app.dependency_overrides.pop(get_async_db, None)


@dataclass(frozen=True)
class SignedIn:
    """What a browser holds after a Magic link sign-in: the fragment's access token and expiry."""

    access_token: str
    expires_at: str


def magic_link_token(link_url: str) -> str:
    """The token query parameter of an emailed Magic link."""
    return parse_qs(urlsplit(link_url).query)["token"][0]


def callback_fragment(location: str) -> dict[str, str]:
    """The parameters in the fragment of a frontend callback redirect."""
    return {key: values[0] for key, values in parse_qs(urlsplit(location).fragment).items()}


@pytest.fixture
def sign_in_by_magic_link(db, auth_outbox) -> Callable[[AsyncClient, str], Awaitable[SignedIn]]:
    """
    Sign a browser in over HTTP: request a Magic link, open it from the outbox,
    and keep the refresh cookie in the browser. Each call starts a new Session.
    """

    async def _sign_in(browser: AsyncClient, email: str) -> SignedIn:
        # Earlier links for this email would hold the request cool-down: age them past it.
        links = (await db.execute(select(MagicLink).where(MagicLink.email == email))).scalars()
        for link in links:
            link.sent_at = link.sent_at - timedelta(minutes=2)
        await db.commit()

        sent_before = len(auth_outbox.messages)
        requested = await browser.post("/api/v1/login/magic-link/request", json={"email": email})
        assert requested.status_code == 200
        assert len(auth_outbox.messages) == sent_before + 1
        link_url = auth_outbox.messages[-1].link_url

        opened = await browser.get(
            "/api/v1/login/magic-link", params={"token": magic_link_token(link_url)}
        )
        assert opened.status_code == 303, opened.text
        fragment = callback_fragment(opened.headers["location"])
        assert "refresh_token" in browser.cookies
        return SignedIn(access_token=fragment["access_token"], expires_at=fragment["expires_at"])

    return _sign_in


@pytest.fixture
def sign_in_with_google(fake_google) -> Callable[[AsyncClient, GoogleClaims], Awaitable[Response]]:
    """
    Run a browser through Google sign-in: start it, then land on the callback as
    Google would, with the fake answering the code exchange with these claims.
    Returns the callback response (not followed).
    """

    async def _sign_in(browser: AsyncClient, claims: GoogleClaims) -> Response:
        fake_google.claims = claims
        started = await browser.get("/api/v1/login/google")
        assert started.status_code == 200
        state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
        return await browser.get(
            "/api/v1/oauth/google/callback", params={"code": "auth-code", "state": state}
        )

    return _sign_in


@pytest_asyncio.fixture
async def authed_client(new_browser, sign_in_by_magic_link, user) -> AsyncClient:
    """
    A browser signed in as `user` by a real Magic link sign-in. It sends the issued
    access token as a bearer header, so every request runs real token verification.
    """
    browser = new_browser()
    signed_in = await sign_in_by_magic_link(browser, user.email)
    browser.headers["Authorization"] = f"Bearer {signed_in.access_token}"
    return browser


async def _set_suspended_until(db: AsyncSession, email: str, until: Optional[datetime]) -> None:
    # Operators suspend a User by setting `suspended_until` directly (no endpoint yet).
    found = (await db.execute(select(User).where(User.email == email))).scalar_one()
    found.suspended_until = until
    await db.commit()


@pytest.fixture
def suspend_user(db) -> Callable[[str], Awaitable[None]]:
    """Suspend the User with this email until a day from now."""

    async def _suspend(email: str) -> None:
        await _set_suspended_until(db, email, datetime.now(timezone.utc) + timedelta(days=1))

    return _suspend


@pytest.fixture
def lift_suspension(db) -> Callable[[str], Awaitable[None]]:
    """End the suspension of the User with this email."""

    async def _lift(email: str) -> None:
        await _set_suspended_until(db, email, None)

    return _lift


@pytest.fixture
def fake_posthog(monkeypatch) -> MagicMock:
    """Replace the PostHog client the global handler captures exceptions with."""
    fake = MagicMock()
    monkeypatch.setattr(exceptions_module, "posthog_client", fake)
    return fake


def _assert_reported(fake_posthog: MagicMock, response: Response, status_code: int) -> None:
    assert response.status_code == status_code
    error_id = response.json()["error_id"]
    assert re.fullmatch(r"[0-9a-f]{8}", error_id)
    fake_posthog.capture_exception.assert_called_once()
    assert fake_posthog.capture_exception.call_args.kwargs["properties"]["error_id"] == error_id


@pytest.fixture
def assert_reported_500(fake_posthog) -> Callable[[Response], None]:
    """
    Assert the global handler's contract: a 500 whose body carries an
    `error_id`, captured in PostHog exactly once under that same ID.
    """
    return lambda response: _assert_reported(fake_posthog, response, 500)


@pytest.fixture
def assert_reported_502(fake_posthog) -> Callable[[Response], None]:
    """
    Assert the billing-provider failure contract: a 502 whose body carries an
    `error_id`, captured in PostHog exactly once under that same ID.
    """
    return lambda response: _assert_reported(fake_posthog, response, 502)
