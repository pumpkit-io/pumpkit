from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.ids import ulid_with_prefix
from app.core.security import hash_token
from app.db.models import RefreshToken, SignInMethod


async def create_refresh_token(
    db: AsyncSession,
    user_id: str,
    refresh_token: str,
    sign_in_method: SignInMethod,
    session_id: Optional[str] = None,
    previous_token: Optional[RefreshToken] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> RefreshToken:
    """
    Store a refresh token, optionally rotating the previous token of the same Session.
    Without a Session ID or a previous token, the refresh token starts a new Session.
    """

    refresh_token_hash = hash_token(refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    resolved_session_id = (
        session_id
        or (previous_token.session_id if previous_token else None)
        or ulid_with_prefix("session")
    )

    token = RefreshToken(
        user_id=user_id,
        sign_in_method=sign_in_method,
        session_id=resolved_session_id,
        refresh_token_hash=refresh_token_hash,
        expires_at=expires_at,
        ip=ip,
        user_agent=user_agent,
    )

    db.add(token)
    await db.flush()

    if previous_token is not None:
        # Rotate the previous token
        now = datetime.now(timezone.utc)
        previous_token.is_revoked = True
        previous_token.revoked_at = now
        previous_token.rotated_at = now
        previous_token.replaced_by = token.id
    await db.commit()
    await db.refresh(token)
    return token


async def get_active_refresh_token_by_hash(
    db: AsyncSession,
    token_hash: str,
    lock_for_update: bool = False,
) -> Optional[RefreshToken]:
    """
    Get an active (non-revoked and non-expired) refresh token by its hash.

    Args:
        db: Database session
        token_hash: Hashed refresh token to look up
        lock_for_update: If True, the db's row corresponding to the selected refresh token
            gets locked by this db session using the SELECT FOR UPDATE statement until the
            transaction commits. This prevents multiple concurrent requests from rotating the same
            refresh token and creating multiple new tokens in the same Session.
    """
    query = select(RefreshToken).where(
        RefreshToken.refresh_token_hash == token_hash,
        ~RefreshToken.is_revoked,
        RefreshToken.expires_at > datetime.now(timezone.utc),
    )
    if lock_for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_refresh_token_by_hash(
    db: AsyncSession,
    token_hash: str,
) -> Optional[RefreshToken]:
    """
    Get a refresh token (even if revoked or expired) by its hash.
    """
    query = select(RefreshToken).where(
        RefreshToken.refresh_token_hash == token_hash,
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def revoke_session(
    db: AsyncSession,
    session_id: str,
) -> None:
    """
    Revoke every refresh token of a Session.
    """
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.session_id == session_id, ~RefreshToken.is_revoked)
        .values(is_revoked=True, revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def revoke_refresh_token(
    db: AsyncSession,
    token: RefreshToken,
) -> None:
    """Revoke a specific refresh token."""
    token.is_revoked = True
    token.revoked_at = datetime.now(timezone.utc)
    await db.commit()


async def revoke_all_user_sessions(db: AsyncSession, user_id: str) -> None:
    """Revoke every Session of a User."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, ~RefreshToken.is_revoked)
        .values(is_revoked=True, revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()
