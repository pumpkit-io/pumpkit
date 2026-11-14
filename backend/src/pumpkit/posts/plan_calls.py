"""
The per-User hourly cap on plan calls (ADR 0025). Planning is free to the User but each call is
paid for, so it is capped on top of the per-minute write rate.
"""

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.users as users_service
from pumpkit.core.errors import RetryLaterError
from pumpkit.posts import service

PLAN_CALLS_PER_HOUR = 20
PLAN_CALL_WINDOW = timedelta(hours=1)


async def count_plan_call(db: AsyncSession, *, user_id: str, now: datetime) -> None:
    """
    Count one plan call against the cap, or raise `RetryLaterError` once the User is at it.
    Counted before the call, so a failed one counts too. Locks the User until the caller commits.
    """
    # Serializes a User's requests, so two at once can't both take the last plan call of the hour.
    await users_service.lock_user_id(db, user_id=user_id)
    counted_since = now - PLAN_CALL_WINDOW
    called_at = await service.plan_calls_since(db, user_id=user_id, since=counted_since)
    if len(called_at) >= PLAN_CALLS_PER_HOUR:
        surplus = len(called_at) - PLAN_CALLS_PER_HOUR
        raise RetryLaterError(
            f"You've planned {PLAN_CALLS_PER_HOUR} briefs in the last hour.",
            retry_at=called_at[surplus] + PLAN_CALL_WINDOW,
            now=now,
        )
    await service.log_plan_call(db, user_id=user_id, now=now, counted_since=counted_since)
