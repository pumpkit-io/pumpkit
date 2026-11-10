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

from pumpkit.auth.models import User
from pumpkit.auth.service.users import may_fill_photo
from pumpkit.core.errors import AppError, ConflictError
from pumpkit.core.security import decrypt, encrypt, generate_token, hash_token
from pumpkit.core.time import as_utc
from pumpkit.x_connection.models import PendingXAuthorization, XConnection
from pumpkit.x_connection.x_publisher import (
    X_MEDIA_SCOPE,
    X_SCOPES,
    XAccount,
    XTokens,
    new_code_verifier,
)

LIFETIME = timedelta(minutes=10)
# Where the User connects or reconnects X, which takes a browser.
X_CONNECTION_PAGE = "/settings"


class XConnectionNotFoundError(AppError):
    status_code = 404
    public_detail = "You haven't connected an X account."


class XPhotoNotFoundError(AppError):
    status_code = 404
    public_detail = "Your X account has no photo."


class XPhotoUnavailableError(AppError):
    status_code = 502
    public_detail = "Couldn't use your X photo. Try again."


def needs_reconnect_for_media(connection: XConnection) -> bool:
    """Whether X's consent predates `media.write`, so X would refuse this connection's uploads."""
    return X_MEDIA_SCOPE not in connection.scopes.split()


def needs_reconnect(connection: XConnection, user: User) -> bool:
    return connection.needs_reconnect or (
        user.x_user_id is not None and not set(X_SCOPES.split()).issubset(connection.scopes.split())
    )


async def check_takes_media(db: AsyncSession, *, user_id: str) -> None:
    """
    Refuses Media while the User's X connection lacks `media.write` (ADR 0021). Without an
    X connection Media is taken: connecting later asks for every scope.
    """
    connection = await get_connection(db, user_id=user_id)
    if connection is not None and needs_reconnect_for_media(connection):
        raise ConflictError(
            "Reconnect X so Pumpkit can post media on your X account.",
            fix_page=X_CONNECTION_PAGE,
            code="X_RECONNECT_FOR_MEDIA",
        )


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
    connection.photo_url = account.photo_url
    connection.photo_offer_answered_at = None
    connection.access_token_encrypted = encrypt(tokens.access_token)
    connection.refresh_token_encrypted = encrypt(tokens.refresh_token)
    connection.access_token_expires_at = tokens.expires_at
    # X may leave out `scope` when it grants exactly what was asked for (RFC 6749, 5.1).
    connection.scopes = tokens.scope or X_SCOPES
    connection.needs_reconnect = False
    connection.updated_at = now
    await db.flush()
    return connection


def offers_photo(connection: XConnection, user: User) -> bool:
    """Whether to offer the X account's photo as the User's Photo, once per connect."""
    return (
        may_fill_photo(user)
        and connection.photo_url is not None
        and connection.photo_offer_answered_at is None
    )


async def answer_photo_offer(db: AsyncSession, connection: XConnection, *, now: datetime) -> None:
    """Flushes."""
    connection.photo_offer_answered_at = now
    await db.flush()


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
    # A refresh answer may leave out `scope`, which then means the scopes granted before.
    if tokens.scope:
        connection.scopes = tokens.scope
    connection.updated_at = now
    await db.flush()


async def save_account(
    db: AsyncSession, connection: XConnection, *, account: XAccount, now: datetime
) -> None:
    """Keep what a later users/me read says about the X account. Flushes."""
    connection.subscription_type = account.subscription_type
    connection.photo_url = account.photo_url
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
    started = StartedAuthorization(
        state="reconnect." + generate_token(32), code_verifier=new_code_verifier()
    )
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
