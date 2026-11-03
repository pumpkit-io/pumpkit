"""
The Media service: Media records, their files in the `FileStorage`, and their places on a Post's
Text. Flush-only; the mediators commit. `scheduling` imports it to copy, publish and delete Media.
"""

import io
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import BinaryIO, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.core.errors import ConflictError, NotFoundError
from pumpkit.core.logging import logger
from pumpkit.core.storage import FileStorage
from pumpkit.posts.formats import part_name
from pumpkit.posts.media_files import IMAGES_PER_PART, CheckedMedia, part_full
from pumpkit.posts.models import Media, Post, TextMedia
from pumpkit.posts.schemas import MediaResponse


def file_key(media_id: str) -> str:
    return f"media/{media_id}/file"


def preview_key(media_id: str) -> str:
    return f"media/{media_id}/preview"


def preview_url(media_id: str) -> str:
    return f"/media/{media_id}/preview"


def media_response(media: Media) -> MediaResponse:
    return MediaResponse(
        id=media.id,
        kind=media.kind,
        preview_url=preview_url(media.id),
        width=media.width,
        height=media.height,
        alt_text=media.alt_text,
    )


def text_media_by_part(post: Post) -> list[list[Media]]:
    """Each of the Text's Parts' Media in order, one list per Part."""
    by_part: list[list[Media]] = [[] for _ in post.text_parts or []]
    for placed in post.text_media:
        if placed.part_index < len(by_part):
            by_part[placed.part_index].append(placed.media)
    return by_part


def move_dropped_parts_media(post: Post) -> None:
    """
    Moves the Media of Parts the Text no longer has onto its last Part, after that Part's own, in
    order. The Post page's `useTextMedia` moves tiles the same way. Not flushed.
    """
    last = len(post.text_parts or []) - 1
    position = max((p.position for p in post.text_media if p.part_index == last), default=-1)
    dropped = [p for p in post.text_media if p.part_index > last]
    for placed in sorted(dropped, key=lambda p: (p.part_index, p.position)):
        position += 1
        placed.part_index, placed.position = last, position


def check_dropped_parts_media_movable(post: Post, *, part_count: int, live_count: int) -> None:
    """
    Refuses a Text of `part_count` Parts whose last Part is already on X while a Part it drops
    holds Media: a live Part's Media is set, so the moved Media would be stuck there unseen.
    """
    if part_count > live_count or all(p.part_index < part_count for p in post.text_media):
        return
    raise ConflictError(
        f"Part {part_count} is already on X, so it can't take the media of the parts this "
        "version drops."
    )


def check_text_part_room(post: Post, *, part_index: int) -> None:
    """Refuses a Part of the Text that holds as many images as X takes on one X post."""
    count = len(post.text_parts or [])
    if not 0 <= part_index < count:
        raise NotFoundError(f"This post's text has no part {part_index + 1}.")
    check_part_room(text_media_by_part(post), part_index=part_index)


def check_part_room(media_by_part: list[list[Media]], *, part_index: int) -> None:
    """Refuses Part `part_index` of a Text or Scheduled post when it can't take another image."""
    if len(media_by_part[part_index]) >= IMAGES_PER_PART:
        name = part_name(part_index + 1, len(media_by_part)) or "this post"
        raise part_full(name.capitalize())


async def attach_to_text(
    db: AsyncSession,
    storage: FileStorage,
    *,
    post: Post,
    part_index: int,
    checked: CheckedMedia,
    file: BinaryIO,
    now: datetime,
    alt_text: Optional[str] = None,
) -> Media:
    """Store `checked`'s file and preview, and add it last on the Text's Part. Flushes."""
    media = await store(
        db, storage, user_id=post.user_id, checked=checked, file=file, now=now, alt_text=alt_text
    )
    on_part = [p.position for p in post.text_media if p.part_index == part_index]
    async with files_deleted_on_failure(storage, media):
        post.text_media.append(
            TextMedia(
                media=media,
                post_id=post.id,
                part_index=part_index,
                position=max(on_part, default=-1) + 1,
            )
        )
        await db.flush()
    return media


async def store(
    db: AsyncSession,
    storage: FileStorage,
    *,
    user_id: str,
    checked: CheckedMedia,
    file: BinaryIO,
    now: datetime,
    alt_text: Optional[str] = None,
) -> Media:
    """
    A new Media of the User's, with `checked`'s file and preview stored, placed nowhere yet.
    Flushes. Wrap the work up to the commit in `files_deleted_on_failure`.
    """
    media = Media(
        user_id=user_id,
        kind=checked.kind,
        content_type=checked.content_type,
        byte_size=checked.byte_size,
        width=checked.width,
        height=checked.height,
        alt_text=alt_text,
        created_at=now,
    )
    db.add(media)
    await db.flush()
    file.seek(0)
    async with files_deleted_on_failure(storage, media):
        await storage.put(file_key(media.id), file)
        await storage.put(preview_key(media.id), io.BytesIO(checked.preview))
    media.file_key = file_key(media.id)
    media.preview_key = preview_key(media.id)
    await db.flush()
    return media


@asynccontextmanager
async def files_deleted_on_failure(storage: FileStorage, media: Media) -> AsyncIterator[None]:
    """
    Deletes the files `store` stored for `media` when the block raises, since its record then
    never commits. Best effort: the publisher's sweep deletes what this misses.
    """
    try:
        yield
    except BaseException:
        for key in (file_key(media.id), preview_key(media.id)):
            try:
                await storage.delete(key)
            except Exception:
                logger.exception("Deleting %s after a failed attach failed", key)
        raise


def text_media_on(post: Post, *, media_id: str) -> TextMedia:
    """Where the Media sits on the Post's Text. Raises `NotFoundError` when it isn't there."""
    placed = next((p for p in post.text_media if p.media_id == media_id), None)
    if placed is None:
        raise NotFoundError("This post's text has no such media.")
    return placed


def remove_from_text(post: Post, placed: TextMedia) -> None:
    """Take the Media off the Text. The record and its file stay until nothing references them."""
    post.text_media.remove(placed)


async def delete(db: AsyncSession, storage: FileStorage, media: Media) -> None:
    """
    Delete the Media's files, then its record. Flushes. Raises `OSError` when a file can't be
    deleted, leaving the record so a later try finds it.
    """
    for key in (media.file_key, media.preview_key):
        if key is not None:
            await storage.delete(key)
    await db.delete(media)
    await db.flush()


async def get_user_media(db: AsyncSession, *, user_id: str, media_id: str) -> Optional[Media]:
    """The User's Media, or None when it isn't theirs."""
    result = await db.execute(select(Media).where(Media.id == media_id, Media.user_id == user_id))
    return result.scalar_one_or_none()
