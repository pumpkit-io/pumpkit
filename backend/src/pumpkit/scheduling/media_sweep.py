"""
Deleting Media nothing references any more: not the Text of a Post, nor a Scheduled post. That is
Media removed or replaced, left by an upload whose Media was dropped, or the Media of a deleted
Post. The publisher's pass runs the sweep. A Published Post's Media stays, with its preview, as
long as its Scheduled post references it.
"""

from datetime import datetime, timedelta

from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.users as users_service
import pumpkit.posts.media as media_service
from pumpkit.core.logging import logger
from pumpkit.core.storage import FileStorage
from pumpkit.posts.models import Media, TextMedia
from pumpkit.scheduling.models import ScheduledPostMedia

# Longer than any request or publish step that holds a Media before referencing it.
UNREFERENCED_GRACE = timedelta(hours=1)
_USERS_PER_SWEEP = 100


async def delete_unreferenced_media(
    db: AsyncSession, storage: FileStorage, *, now: datetime
) -> None:
    """
    Delete each Media nothing references, created more than `UNREFERENCED_GRACE` before `now`,
    with its files. Commits once per User.
    """
    cutoff = now - UNREFERENCED_GRACE
    users = await db.execute(
        _unreferenced(select(Media.user_id).distinct(), cutoff=cutoff).limit(_USERS_PER_SWEEP)
    )
    await db.commit()
    for user_id in users.scalars().all():
        # Scheduling a Post copies the Text's references under this lock, so none lands mid-sweep.
        await users_service.lock_user_id(db, user_id=user_id)
        found = await db.execute(
            _unreferenced(select(Media), cutoff=cutoff).where(Media.user_id == user_id)
        )
        for media in found.scalars().all():
            try:
                await media_service.delete(db, storage, media)
            except (OSError, ValueError):
                logger.exception("Deleting the files of unreferenced %s failed", media.id)
        await db.commit()


def _unreferenced[T: tuple](query: Select[T], *, cutoff: datetime) -> Select[T]:
    return query.where(
        Media.created_at < cutoff,
        ~exists().where(TextMedia.media_id == Media.id),
        ~exists().where(ScheduledPostMedia.media_id == Media.id),
    )
