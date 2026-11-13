from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.core.time import as_utc
from pumpkit.positioning import service
from pumpkit.positioning.models import Positioning
from pumpkit.positioning.schemas import PositioningResponse


def _response(positioning: Optional[Positioning]) -> PositioningResponse:
    if positioning is None:
        return PositioningResponse(text=None, saved_at=None)
    return PositioningResponse(text=positioning.text, saved_at=as_utc(positioning.saved_at))


async def get_positioning(db: AsyncSession, user: User) -> PositioningResponse:
    return _response(await service.get_positioning(db, user_id=user.id))


async def save_positioning(
    db: AsyncSession, user: User, text: str, now: datetime
) -> PositioningResponse:
    positioning = await service.save_positioning(db, user_id=user.id, text=text, now=now)
    await db.commit()
    return _response(positioning)
