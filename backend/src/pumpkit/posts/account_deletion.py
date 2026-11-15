from collections.abc import Collection
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.posts.models import AccountFileDeletion, Media


async def queue_files(db: AsyncSession, *, user_id: str) -> None:
    media = await db.scalars(select(Media).where(Media.user_id == user_id))
    for item in media:
        for key in (item.file_key, item.preview_key):
            if key is not None:
                await db.merge(AccountFileDeletion(key=key))
    await db.flush()


async def pending_files(
    db: AsyncSession, *, keys: Optional[Collection[str]] = None
) -> list[AccountFileDeletion]:
    """Lock the queued files no other sweep holds, only `keys` when given so others stay free."""
    query = select(AccountFileDeletion)
    if keys is not None:
        query = query.where(AccountFileDeletion.key.in_(keys))
    return list(
        await db.scalars(query.order_by(AccountFileDeletion.key).with_for_update(skip_locked=True))
    )
