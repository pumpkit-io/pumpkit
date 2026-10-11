"""
X connections and their tokens, encrypted at rest, and pending X authorizations: the OAuth
state and PKCE verifier of a consent screen in progress.
Flushes and never commits: the calling mediator owns the transaction.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.core.errors import AppError
from pumpkit.core.security import decrypt, encrypt, generate_token, hash_token
from pumpkit.core.time import as_utc
from pumpkit.x_connection.models import PendingXAuthorization, XConnection
from pumpkit.x_connection.x_publisher import XAccount, XTokens, new_code_verifier

LIFETIME = timedelta(minutes=10)


class XConnectionNotFoundError(AppError):
    status_code = 404
    public_detail = "You haven't connected an X account."


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


@dataclass(frozen=True)
class StartedAuthorization:
    """The clear state and verifier exist only here, in X's URL and in the encrypted row."""

    state: str
    code_verifier: str


async def start(db: AsyncSession, *, user_id: str, now: datetime) -> StartedAuthorization:
    """Store a new pending authorization for the User, dropping every expired one. Flushes."""
    await db.execute(delete(PendingXAuthorization).where(PendingXAuthorization.expires_at <= now))
    started = StartedAuthorization(state=generate_token(32), code_verifier=new_code_verifier())
    db.add(
        PendingXAuthorization(
            state_hash=hash_token(started.state),
            user_id=user_id,
            code_verifier_encrypted=encrypt(started.code_verifier),
            created_at=now,
            expires_at=now + LIFETIME,
        )
    )
    await db.flush()
    return started


async def consume(db: AsyncSession, *, user_id: str, state: str, now: datetime) -> Optional[str]:
    """
    Delete the User's pending authorization for `state` and return its verifier, or None if
    there is none, it expired, or it belongs to another User. The delete decides, so of two
    concurrent completes only one gets the verifier.
    """
    deleted = await db.execute(
        delete(PendingXAuthorization)
        .where(
            PendingXAuthorization.state_hash == hash_token(state),
            PendingXAuthorization.user_id == user_id,
        )
        .returning(PendingXAuthorization.code_verifier_encrypted, PendingXAuthorization.expires_at)
    )
    row = deleted.one_or_none()
    if row is None:
        return None
    code_verifier_encrypted, expires_at = row
    if as_utc(expires_at) <= now:
        return None
    return decrypt(code_verifier_encrypted) or None
