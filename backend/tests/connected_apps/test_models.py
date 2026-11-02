"""Deleting a User takes every Connected app row with it."""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from pumpkit.auth.models import User
from pumpkit.connected_apps.models import (
    AppConnection,
    OAuthAccessToken,
    OAuthAuthorization,
    OAuthClient,
    OAuthRefreshToken,
)
from pumpkit.core.db.base import Base

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


async def test_deleting_a_user_deletes_their_connections_tokens_and_authorizations(tmp_path):
    # The shared test engine leaves SQLite's foreign keys off, which cascades need.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fk.db'}", poolclass=NullPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys_on(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(email="ana@example.com", display_name="Ana")
        client = OAuthClient(
            id="oauth_client_1",
            kind="registered",
            name="Claude",
            redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
            token_endpoint_auth_method="none",
            created_at=NOW,
        )
        session.add_all([user, client])
        await session.flush()
        connection = AppConnection(
            user_id=user.id,
            client_id=client.id,
            scope="pumpkit",
            resource="https://pumpkit.example.org/api/v1/mcp",
            created_at=NOW,
        )
        session.add(connection)
        await session.flush()
        session.add_all(
            [
                OAuthAuthorization(
                    id="authorization_1",
                    client_id=client.id,
                    redirect_uri="https://claude.ai/api/mcp/auth_callback",
                    redirect_uri_was_sent=True,
                    code_challenge="challenge",
                    scope="pumpkit",
                    resource="https://pumpkit.example.org/api/v1/mcp",
                    created_at=NOW,
                    expires_at=NOW + timedelta(minutes=30),
                    user_id=user.id,
                    app_connection_id=connection.id,
                ),
                OAuthRefreshToken(
                    app_connection_id=connection.id,
                    token_hash="refresh",
                    created_at=NOW,
                    expires_at=NOW + timedelta(days=90),
                ),
                OAuthAccessToken(
                    app_connection_id=connection.id,
                    token_hash="access",
                    created_at=NOW,
                    expires_at=NOW + timedelta(hours=1),
                ),
            ]
        )
        await session.commit()

        await session.execute(sa.delete(User).where(User.id == user.id))
        await session.commit()

        for table in (
            "app_connections",
            "oauth_authorizations",
            "oauth_refresh_tokens",
            "oauth_access_tokens",
        ):
            count = await session.scalar(sa.text(f"SELECT count(*) FROM {table}"))
            assert count == 0, table
        assert await session.scalar(sa.text("SELECT count(*) FROM oauth_clients")) == 1
    await engine.dispose()
