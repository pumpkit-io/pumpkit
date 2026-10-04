"""
The Magic link module: issues, redeems and invalidates Magic links.

This module alone owns the token hashing, the expiry, the per-email cool-down
and the handling of concurrent redemptions. Callers get the clear token (or
"cooling down") from `issue`, and an email (or a typed failure) from `redeem`.
It flushes and never commits: the calling mediator owns the transaction.
"""

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Union

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.services.sessions import ClientInfo
from app.core.config import settings
from app.core.datetimes import as_utc
from app.core.security import generate_token, hash_token
from app.db.models import MagicLink

# Minimum time between two Magic links issued for the same email.
COOLDOWN = timedelta(seconds=60)


@dataclass(frozen=True)
class IssuedMagicLink:
    """A newly issued Magic link. The clear token exists only here and in the email."""

    token: str
    expires_in_minutes: int


@dataclass(frozen=True)
class CoolingDown:
    """No link was issued: one was issued for this email less than `COOLDOWN` ago."""


IssueResult = Union[IssuedMagicLink, CoolingDown]


class RedemptionFailureReason(enum.Enum):
    NOT_FOUND = "not_found"
    ALREADY_CONSUMED = "already_consumed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class RedeemedMagicLink:
    """A consumed Magic link. `email` is the address it was issued for, never the URL's."""

    email: str


@dataclass(frozen=True)
class RedemptionFailure:
    reason: RedemptionFailureReason


RedeemResult = Union[RedeemedMagicLink, RedemptionFailure]


async def issue(
    db: AsyncSession,
    *,
    email: str,
    user_id: Optional[str],
    client: ClientInfo,
    now: datetime,
) -> IssueResult:
    """
    Issue a Magic link for `email`, unless one was issued within the cool-down.
    Earlier unconsumed links for that email stop working.
    """
    latest = await _latest_for_email(db, email)
    if latest is not None and now - as_utc(latest.sent_at) < COOLDOWN:
        return CoolingDown()

    await db.execute(
        update(MagicLink)
        .where(MagicLink.email == email, MagicLink.consumed_at.is_(None))
        .values(consumed_at=now)
    )

    duration_minutes = settings.MAGIC_LINK_TOKEN_DURATION_MINUTES
    token = generate_token(num_bytes=settings.MAGIC_LINK_TOKEN_NUM_BYTES)
    db.add(
        MagicLink(
            user_id=user_id,
            email=email,
            token_hash=hash_token(token),
            sent_at=now,
            expires_at=now + timedelta(minutes=duration_minutes),
            requester_ip=client.ip,
            requester_user_agent=client.user_agent,
        )
    )
    await db.flush()
    return IssuedMagicLink(token=token, expires_in_minutes=duration_minutes)


async def invalidate(db: AsyncSession, *, token: str) -> None:
    """
    Void a just-issued Magic link whose email could not be sent.

    The row is deleted rather than marked consumed: a link that never reached
    the User must not hold the per-email cool-down.
    """
    await db.execute(delete(MagicLink).where(MagicLink.token_hash == hash_token(token)))
    await db.flush()


async def redeem(db: AsyncSession, *, token: str, now: datetime) -> RedeemResult:
    """
    Consume the Magic link for `token` and return the email it was issued for.

    Consumption is one conditional UPDATE, so of two concurrent redemptions only
    one wins; the loser sees the link as already consumed. It runs before any
    read, so the database serialises the race instead of failing a stale read.
    """
    token_hash = hash_token(token)
    result = await db.execute(
        update(MagicLink)
        .where(MagicLink.token_hash == token_hash, MagicLink.consumed_at.is_(None))
        .values(consumed_at=now)
        .returning(MagicLink.email, MagicLink.expires_at)
    )
    consumed = result.one_or_none()
    if consumed is not None:
        if as_utc(consumed.expires_at) <= now:
            return RedemptionFailure(RedemptionFailureReason.EXPIRED)
        return RedeemedMagicLink(email=consumed.email)

    exists = await db.scalar(select(MagicLink.id).where(MagicLink.token_hash == token_hash))
    if exists is None:
        return RedemptionFailure(RedemptionFailureReason.NOT_FOUND)
    return RedemptionFailure(RedemptionFailureReason.ALREADY_CONSUMED)


async def _latest_for_email(db: AsyncSession, email: str) -> Optional[MagicLink]:
    """The most recently issued Magic link for an email, whatever its status."""
    result = await db.execute(
        select(MagicLink)
        .where(MagicLink.email == email)
        .order_by(MagicLink.sent_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
