"""
X connections and their tokens, encrypted at rest.
Flushes and never commits: the calling mediator owns the transaction.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt, encrypt
from app.core.x_publisher import XAccount, XTokens
from app.db.models import XConnection


async def get_connection(db: AsyncSession, *, user_id: str) -> Optional[XConnection]:
    result = await db.execute(select(XConnection).where(XConnection.user_id == user_id))
    return result.scalar_one_or_none()


async def get_connection_by_x_user_id(db: AsyncSession, *, x_user_id: str) -> Optional[XConnection]:
    result = await db.execute(select(XConnection).where(XConnection.x_user_id == x_user_id))
    return result.scalar_one_or_none()


async def save_connection(
    db: AsyncSession, *, user_id: str, account: XAccount, tokens: XTokens, now: datetime
) -> XConnection:
    """Create the User's X connection, or replace the one they have, whichever X account. Flushes."""
    connection = await get_connection(db, user_id=user_id)
    if connection is None:
        connection = XConnection(user_id=user_id, created_at=now)
        db.add(connection)
    connection.x_user_id = account.user_id
    connection.handle = account.handle
    connection.subscription_type = account.subscription_type
    connection.access_token_encrypted = encrypt(tokens.access_token)
    connection.refresh_token_encrypted = encrypt(tokens.refresh_token)
    connection.access_token_expires_at = tokens.expires_at
    connection.scopes = tokens.scope
    connection.needs_reconnect = False
    connection.updated_at = now
    await db.flush()
    return connection


async def lock_connection(db: AsyncSession, *, user_id: str) -> Optional[XConnection]:
    """
    The User's X connection, locked and reloaded until the transaction ends, so only one
    process refreshes its rotating refresh token. SQLite has no row locks: there it only reloads.
    """
    result = await db.execute(
        select(XConnection)
        .where(XConnection.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def save_tokens(
    db: AsyncSession, connection: XConnection, *, tokens: XTokens, now: datetime
) -> None:
    """Keep refreshed tokens: X has already retired the old refresh token. Flushes."""
    connection.access_token_encrypted = encrypt(tokens.access_token)
    connection.refresh_token_encrypted = encrypt(tokens.refresh_token)
    connection.access_token_expires_at = tokens.expires_at
    connection.scopes = tokens.scope
    connection.updated_at = now
    await db.flush()


async def save_subscription_type(
    db: AsyncSession, connection: XConnection, *, subscription_type: Optional[str], now: datetime
) -> None:
    """Flushes."""
    connection.subscription_type = subscription_type
    connection.updated_at = now
    await db.flush()


async def flag_needs_reconnect(db: AsyncSession, connection: XConnection, *, now: datetime) -> None:
    """X refuses the connection's tokens for good. Flushes."""
    connection.needs_reconnect = True
    connection.updated_at = now
    await db.flush()


def access_token(connection: XConnection) -> str:
    """The clear access token; "" when it can't be decrypted."""
    return decrypt(connection.access_token_encrypted)


def refresh_token(connection: XConnection) -> str:
    """The clear refresh token; "" when it can't be decrypted."""
    return decrypt(connection.refresh_token_encrypted)


async def delete_connection(db: AsyncSession, connection: XConnection) -> None:
    """Flushes."""
    await db.delete(connection)
    await db.flush()
