"""
Storage of refresh tokens. A Session is the set of refresh tokens sharing a `session_id`.
Only the Sessions module (`api/services/sessions.py`) calls this. It flushes and never commits.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_token
from app.db.models import RefreshToken, SignInMethod


async def create_refresh_token(
    db: AsyncSession,
    user_id: str,
    refresh_token: str,
    sign_in_method: SignInMethod,
    session_id: str,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> RefreshToken:
    """Store the hash of a refresh token issued in the given Session."""
    token = RefreshToken(
        user_id=user_id,
        sign_in_method=sign_in_method,
        session_id=session_id,
        refresh_token_hash=hash_token(refresh_token),
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        ip=ip,
        user_agent=user_agent,
    )
    db.add(token)
    await db.flush()
    return token


async def get_refresh_token_by_hash(
    db: AsyncSession,
    token_hash: str,
    lock_for_update: bool = False,
) -> Optional[RefreshToken]:
    """
    Get a refresh token, whatever its status, by its hash.

    With `lock_for_update`, the row stays locked (SELECT ... FOR UPDATE) until the
    transaction ends, so concurrent requests can't rotate the same token twice.
    """
    query = select(RefreshToken).where(RefreshToken.refresh_token_hash == token_hash)
    if lock_for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def mark_rotated(db: AsyncSession, token: RefreshToken, replaced_by: RefreshToken) -> None:
    """Retire a refresh token that was exchanged for a newer one in the same Session."""
    now = datetime.now(timezone.utc)
    token.is_revoked = True
    token.revoked_at = now
    token.rotated_at = now
    token.replaced_by = replaced_by.id
    await db.flush()


async def revoke_session(db: AsyncSession, session_id: str) -> None:
    await _revoke_where(db, RefreshToken.session_id == session_id)


async def revoke_all_user_sessions(db: AsyncSession, user_id: str) -> None:
    await _revoke_where(db, RefreshToken.user_id == user_id)


async def _revoke_where(db: AsyncSession, criterion: ColumnElement[bool]) -> None:
    await db.execute(
        update(RefreshToken)
        .where(criterion, ~RefreshToken.is_revoked)
        .values(is_revoked=True, revoked_at=datetime.now(timezone.utc))
    )
    await db.flush()
