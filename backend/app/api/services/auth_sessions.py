from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.ids import ulid_with_prefix
from app.core.security import hash_token
from app.db.models import AuthMethod, AuthSession


async def create_auth_session(
    db: AsyncSession,
    user_id: str,
    refresh_token: str,
    auth_method: AuthMethod,
    family_id: Optional[str] = None,
    previous_session: Optional[AuthSession] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> AuthSession:
    """
    Create an auth session and optionally rotate an existing session.
    """

    refresh_token_hash = hash_token(refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    lineage_id = (
        family_id
        or (previous_session.family_id if previous_session else None)
        or ulid_with_prefix("auth_session_family")
    )

    session = AuthSession(
        user_id=user_id,
        auth_method=auth_method,
        family_id=lineage_id,
        refresh_token_hash=refresh_token_hash,
        expires_at=expires_at,
        ip=ip,
        user_agent=user_agent,
    )

    db.add(session)
    await db.flush()

    if previous_session is not None:
        # Rotate the previous session
        now = datetime.now(timezone.utc)
        previous_session.is_revoked = True
        previous_session.revoked_at = now
        previous_session.rotated_at = now
        previous_session.replaced_by = session.id
    await db.commit()
    await db.refresh(session)
    return session


async def get_active_auth_session_by_hash(
    db: AsyncSession,
    token_hash: str,
    lock_for_update: bool = False,
) -> Optional[AuthSession]:
    """
    Get an active (non-revoked and non-expired) authentication session by
    a given hashed refresh token.

    Args:
        db: Database session
        token_hash: Hashed refresh token to look up
        lock_for_update: If True, the db's row corresponding to the selected auth session
            gets locked by this db session using the SELECT FOR UPDATE statement until the
            transaction commits. This prevents multiple concurrent requests from rotating the same
            refresh token and creating multiple new sessions in the same family.
    """
    query = select(AuthSession).where(
        AuthSession.refresh_token_hash == token_hash,
        ~AuthSession.is_revoked,
        AuthSession.expires_at > datetime.now(timezone.utc),
    )
    if lock_for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_auth_session_by_hash(
    db: AsyncSession,
    token_hash: str,
) -> Optional[AuthSession]:
    """
    Get an authentication session (even if revoked or expired) by a given hashed refresh token.
    """
    query = select(AuthSession).where(
        AuthSession.refresh_token_hash == token_hash,
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def revoke_auth_session_family(
    db: AsyncSession,
    family_id: str,
) -> None:
    """
    Revoke all sessions in a family.
    """
    await db.execute(
        update(AuthSession)
        .where(AuthSession.family_id == family_id, ~AuthSession.is_revoked)
        .values(is_revoked=True, revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def revoke_auth_session(
    db: AsyncSession,
    session: AuthSession,
) -> None:
    """Revoke a specific auth session."""
    session.is_revoked = True
    session.revoked_at = datetime.now(timezone.utc)
    await db.commit()


async def revoke_all_user_auth_sessions(db: AsyncSession, user_id: str) -> None:
    """Revoke every auth session for a user."""
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, ~AuthSession.is_revoked)
        .values(is_revoked=True, revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()
