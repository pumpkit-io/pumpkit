from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select
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


async def draft_requests_since(
    db: AsyncSession, *, user_id: str, since: datetime
) -> list[datetime]:
    """When the User made each draft request after `since`, oldest first."""
    query = (
        select(PositioningDraftRequest.requested_at)
        .where(
            PositioningDraftRequest.user_id == user_id,
            PositioningDraftRequest.requested_at > since,
        )
        .order_by(PositioningDraftRequest.requested_at)
    )
    return [as_utc(requested_at) for requested_at in (await db.execute(query)).scalars()]


async def log_draft_request(
    db: AsyncSession, *, user_id: str, now: datetime, counted_since: datetime
) -> None:
    """
    Record one draft request that goes on to read X, and drop the User's requests the limit
    no longer counts: those made at or before `counted_since`. Flushes.
    """
    await db.execute(
        delete(PositioningDraftRequest).where(
            PositioningDraftRequest.user_id == user_id,
            PositioningDraftRequest.requested_at <= counted_since,
        )
    )
    db.add(PositioningDraftRequest(user_id=user_id, requested_at=now))
    await db.flush()
