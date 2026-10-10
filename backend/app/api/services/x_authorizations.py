"""
Pending X authorizations: the OAuth state and PKCE verifier of a consent screen in progress.
Flushes and never commits: the calling mediator owns the transaction.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datetimes import as_utc
from app.core.security import decrypt, encrypt, generate_token, hash_token
from app.core.x_publisher import new_code_verifier
from app.db.models import PendingXAuthorization

LIFETIME = timedelta(minutes=10)


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
