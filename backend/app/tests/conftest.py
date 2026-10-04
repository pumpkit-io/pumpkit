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
    "OPENROUTER_API_KEY": "sk-or-test",
    "POSTHOG_ENABLED": "false",
}
for _key, _value in _TEST_ENV.items():
    os.environ.setdefault(_key, _value)

import pytest_asyncio  # noqa: E402
from fastapi import Depends  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

import app.api.services.users as user_service  # noqa: E402
from app.db import models  # noqa: E402,F401  (registers every table on Base.metadata)
from app.db.base import Base  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.session import get_async_db  # noqa: E402
from app.main import app  # noqa: E402


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
    app.dependency_overrides[user_service.get_user] = _get_user
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
