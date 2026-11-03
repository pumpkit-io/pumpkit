"""
Deleting Media nothing references any more, with its files, the files of Media already published,
and stored files no Media record names. The publisher's pass runs it and it commits as it goes;
`docs/development.md` says what that covers.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import ColumnElement, Select, and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.users as users_service
import pumpkit.posts.media as media_service
from pumpkit.core.logging import logger
from pumpkit.core.storage import FileStorage
from pumpkit.posts.models import Media, TextMedia
from pumpkit.scheduling.models import (
    PUBLISHING,
    ScheduledPost,
    ScheduledPostMedia,
    ScheduledPostPart,
)

# Longer than any request or publish step that holds a Media before referencing it.
UNREFERENCED_GRACE = timedelta(hours=1)
# Listing every stored file costs a walk of the storage and a query per 500 files.
FILES_SWEPT_EVERY = timedelta(hours=1)
_USERS_PER_PAGE = 100
_IDS_PER_QUERY = 500


async def delete_unreferenced_media(
    db: AsyncSession, storage: FileStorage, *, now: datetime
) -> None:
    """
    Delete each Media nothing references, created more than `UNREFERENCED_GRACE` before `now`,
    with its files. Commits once per User; one User's failure is logged and the next goes on.
    """
    cutoff = now - UNREFERENCED_GRACE
    after: Optional[str] = None
    while True:
        query = _unreferenced(select(Media.user_id).distinct(), cutoff=cutoff)
        if after is not None:
            query = query.where(Media.user_id > after)
        page = await db.execute(query.order_by(Media.user_id).limit(_USERS_PER_PAGE))
        user_ids = list(page.scalars().all())
        if not user_ids:
            return
        for user_id in user_ids:
            try:
                await _delete_users_unreferenced(db, storage, user_id=user_id, cutoff=cutoff)
            except Exception:
                await db.rollback()
                logger.exception("Deleting unreferenced Media of %s failed", user_id)
        after = user_ids[-1]


async def delete_published_files(db: AsyncSession, storage: FileStorage) -> None:
    """
    Delete the files of Media whose every place is a live Part, keeping their previews: the
    publish deletes them itself, unless it crashed first or the delete failed. Commits per page.
    """
    after = ""
    while True:
        page = await db.execute(
            select(Media)
            .where(Media.file_key.is_not(None), Media.id > after, _published_only())
            .order_by(Media.id)
            .limit(_IDS_PER_QUERY)
        )
        published = list(page.scalars().all())
        if not published:
            return
        for media in published:
            if media.file_key is None:
                continue
            try:
                await storage.delete(media.file_key)
            except (OSError, ValueError):
                logger.exception("Deleting the published file of %s failed", media.id)
                continue
            media.file_key = None
        await db.commit()
        after = published[-1].id


def _published_only() -> ColumnElement[bool]:
    """On a live Part of a Scheduled post no publish holds, and on no Part not live."""
    part_live = exists().where(
        ScheduledPostPart.scheduled_post_id == ScheduledPostMedia.scheduled_post_id,
        ScheduledPostPart.position == ScheduledPostMedia.part_position,
        ScheduledPostPart.x_post_id.is_not(None),
    )
    settled = exists().where(
        ScheduledPost.id == ScheduledPostMedia.scheduled_post_id,
        ScheduledPost.state != PUBLISHING,
    )
    on_live_part = exists().where(ScheduledPostMedia.media_id == Media.id, part_live, settled)
    on_part_not_live = exists().where(ScheduledPostMedia.media_id == Media.id, ~part_live)
    return and_(on_live_part, ~on_part_not_live)


async def delete_unnamed_files(db: AsyncSession, storage: FileStorage, *, now: datetime) -> None:
    """
    Delete stored Media files written more than `UNREFERENCED_GRACE` before `now` whose Media
    record doesn't exist, left by an attach that never committed, and partial writes as old.
    """
    cutoff = now - UNREFERENCED_GRACE
    await storage.delete_abandoned_writes(media_service.MEDIA_PREFIX, written_before=cutoff)
    keys_by_id: dict[str, list[str]] = {}
    for stored in await storage.list_files(media_service.MEDIA_PREFIX):
        if stored.modified_at < cutoff:
            keys_by_id.setdefault(media_service.media_id_of(stored.key), []).append(stored.key)
    if keys_by_id and not (await db.execute(select(exists().select_from(Media)))).scalar():
        logger.warning(
            "Stored media files kept: the database holds no Media at all. Check the publisher "
            "uses the Instance's database and media volume."
        )
        return
    ids = list(keys_by_id)
    for start in range(0, len(ids), _IDS_PER_QUERY):
        chunk = ids[start : start + _IDS_PER_QUERY]
        named = set((await db.execute(select(Media.id).where(Media.id.in_(chunk)))).scalars())
        for media_id in set(chunk) - named:
            for key in keys_by_id[media_id]:
                try:
                    await storage.delete(key)
                except OSError:
                    logger.exception("Deleting the unnamed file %s failed", key)


async def _delete_users_unreferenced(
    db: AsyncSession, storage: FileStorage, *, user_id: str, cutoff: datetime
) -> None:
    # Scheduling a Post copies the Text's references under this lock, so none lands mid-sweep.
    await users_service.lock_user_id(db, user_id=user_id)
    found = await db.execute(
        _unreferenced(select(Media), cutoff=cutoff).where(Media.user_id == user_id)
    )
    for media in found.scalars().all():
        try:
            await media_service.delete(db, storage, media)
        except OSError:
            logger.exception("Deleting the files of unreferenced %s failed", media.id)
    await db.commit()


def _unreferenced[T: tuple](query: Select[T], *, cutoff: datetime) -> Select[T]:
    return query.where(
        Media.created_at < cutoff,
        ~exists().where(TextMedia.media_id == Media.id),
        ~exists().where(ScheduledPostMedia.media_id == Media.id),
    )
