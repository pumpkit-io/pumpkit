from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.core.time import as_utc
from pumpkit.positioning.models import Positioning, PositioningDraftRequest


async def get_positioning(db: AsyncSession, *, user_id: str) -> Optional[Positioning]:
    return await db.get(Positioning, user_id)


async def save_positioning(
    db: AsyncSession, *, user_id: str, text: str, now: datetime
) -> Positioning:
    """Make `text` the User's Positioning, in place of any they had. Flushes."""
    positioning = await db.get(Positioning, user_id)
    if positioning is None:
        try:
            async with db.begin_nested():
                positioning = Positioning(user_id=user_id, text=text, saved_at=now)
                db.add(positioning)
            return positioning
        except IntegrityError:
            # A concurrent first save inserted the row; this one overwrites it.
            positioning = await db.get(Positioning, user_id, populate_existing=True)
            if positioning is None:
                raise
    positioning.text = text
    positioning.saved_at = now
    await db.flush()
    return positioning


@dataclass(frozen=True)
class DraftRequestCount:
    count: int
    # When the oldest counted request was made; None when none was.
    oldest: Optional[datetime]


async def count_draft_requests(
    db: AsyncSession, *, user_id: str, since: datetime
) -> DraftRequestCount:
    """The User's draft requests made after `since`."""
    query = select(func.count(), func.min(PositioningDraftRequest.requested_at)).where(
        PositioningDraftRequest.user_id == user_id, PositioningDraftRequest.requested_at > since
    )
    count, oldest = (await db.execute(query)).one()
    return DraftRequestCount(count=count, oldest=None if oldest is None else as_utc(oldest))


async def log_draft_request(db: AsyncSession, *, user_id: str, now: datetime) -> None:
    """Record one draft request that goes on to read X. Flushes."""
    db.add(PositioningDraftRequest(user_id=user_id, requested_at=now))
    await db.flush()
