from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.positioning.models import Positioning


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
