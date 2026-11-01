"""Consent requests and the authorization codes approving one hands out. Flushes, never commits."""

import base64
import hashlib
import hmac
from datetime import datetime
from typing import Optional, cast

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.connected_apps.models import AppConnection, OAuthAuthorization, OAuthClient
from pumpkit.connected_apps.service.tokens import AUTHORIZATION_REQUEST_LIFETIME, CODE_LIFETIME
from pumpkit.core.security import generate_token, hash_token


async def create_pending(
    db: AsyncSession,
    *,
    client_id: str,
    redirect_uri: str,
    redirect_uri_was_sent: bool,
    code_challenge: str,
    scope: str,
    resource: str,
    state: Optional[str],
    now: datetime,
) -> OAuthAuthorization:
    authorization = OAuthAuthorization(
        id=generate_token(24),
        client_id=client_id,
        redirect_uri=redirect_uri,
        redirect_uri_was_sent=redirect_uri_was_sent,
        code_challenge=code_challenge,
        scope=scope,
        resource=resource,
        state=state,
        created_at=now,
        expires_at=now + AUTHORIZATION_REQUEST_LIFETIME,
    )
    db.add(authorization)
    await db.flush()
    return authorization


async def get_pending(
    db: AsyncSession, authorization_id: str, *, now: datetime
) -> Optional[tuple[OAuthAuthorization, OAuthClient]]:
    """The request and its app, unless the request is unknown, expired or already decided."""
    row = (
        await db.execute(
            select(OAuthAuthorization, OAuthClient)
            .join(OAuthClient, OAuthClient.id == OAuthAuthorization.client_id)
            .where(
                OAuthAuthorization.id == authorization_id,
                OAuthAuthorization.approved.is_(None),
                OAuthAuthorization.expires_at > now,
            )
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


async def approve(
    db: AsyncSession,
    authorization: OAuthAuthorization,
    *,
    user_id: str,
    app_connection_id: str,
    now: datetime,
) -> Optional[str]:
    """The new code, or None when another request decided this one first."""
    code = generate_token(32)
    decided = await _decide(
        db,
        authorization,
        user_id=user_id,
        approved=True,
        app_connection_id=app_connection_id,
        code_hash=hash_token(code),
        code_expires_at=now + CODE_LIFETIME,
        now=now,
    )
    return code if decided else None


async def deny(
    db: AsyncSession, authorization: OAuthAuthorization, *, user_id: str, now: datetime
) -> bool:
    """False when another request decided this one first."""
    return await _decide(db, authorization, user_id=user_id, approved=False, now=now)


async def _decide(
    db: AsyncSession,
    authorization: OAuthAuthorization,
    *,
    user_id: str,
    approved: bool,
    now: datetime,
    **values: object,
) -> bool:
    # Conditional on still being pending, so two concurrent decisions can't both hand out a code.
    result = await db.execute(
        update(OAuthAuthorization)
        .where(OAuthAuthorization.id == authorization.id, OAuthAuthorization.approved.is_(None))
        .values(user_id=user_id, approved=approved, decided_at=now, **values)
        .execution_options(synchronize_session="fetch")
    )
    return cast(CursorResult, result).rowcount == 1


def pkce_matches(verifier: str, challenge: str) -> bool:
    """RFC 7636's S256 check, in constant time."""
    digest = hashlib.sha256(verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return hmac.compare_digest(computed, challenge)


async def find_code(
    db: AsyncSession, code: str, *, now: datetime
) -> Optional[tuple[OAuthAuthorization, AppConnection]]:
    """
    The approved request a code belongs to and the connection it is for, while the code is live
    or once it was exchanged, however long ago: presenting it again is reuse either way.
    """
    row = (
        await db.execute(
            select(OAuthAuthorization, AppConnection)
            .join(AppConnection, AppConnection.id == OAuthAuthorization.app_connection_id)
            .where(
                OAuthAuthorization.code_hash == hash_token(code),
                or_(
                    OAuthAuthorization.exchanged_at.is_not(None),
                    OAuthAuthorization.code_expires_at > now,
                ),
            )
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


async def mark_exchanged(db: AsyncSession, authorization_id: str, *, now: datetime) -> bool:
    """False when another request exchanged the code first."""
    # Conditional, so two concurrent exchanges of one code can't both get tokens.
    result = await db.execute(
        update(OAuthAuthorization)
        .where(OAuthAuthorization.id == authorization_id, OAuthAuthorization.exchanged_at.is_(None))
        .values(exchanged_at=now)
        .execution_options(synchronize_session="fetch")
    )
    return cast(CursorResult, result).rowcount == 1
