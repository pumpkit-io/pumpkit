"""
The Media service: Media records, their files in the `FileStorage`, and their places on a Post's
Text. Flush-only; the mediators commit. `scheduling` imports it to copy, publish and delete Media.
"""

import io
from datetime import datetime
from typing import BinaryIO, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.core.errors import NotFoundError
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
    )


def text_media_by_part(post: Post) -> list[list[Media]]:
    """Each of the Text's Parts' Media in order, one list per Part."""
    by_part: list[list[Media]] = [[] for _ in post.text_parts or []]
    for placed in post.text_media:
        if placed.part_index < len(by_part):
            by_part[placed.part_index].append(placed.media)
    return by_part


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
) -> Media:
    """Store `checked`'s file and preview, and add it last on the Text's Part. Flushes."""
    media = await store(db, storage, user_id=post.user_id, checked=checked, file=file, now=now)
    on_part = [p.position for p in post.text_media if p.part_index == part_index]
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
) -> Media:
    """
    A new Media of the User's, with `checked`'s file and preview stored, placed nowhere yet.
    Flushes. A file stored before a failed commit stays on disk under a key no record names.
    """
    media = Media(
        user_id=user_id,
        kind=checked.kind,
        content_type=checked.content_type,
        byte_size=checked.byte_size,
        width=checked.width,
        height=checked.height,
        created_at=now,
    )
    db.add(media)
    await db.flush()
    file.seek(0)
    await storage.put(file_key(media.id), file)
    await storage.put(preview_key(media.id), io.BytesIO(checked.preview))
    media.file_key = file_key(media.id)
    media.preview_key = preview_key(media.id)
    await db.flush()
    return media


def text_media_on(post: Post, *, media_id: str) -> TextMedia:
    """Where the Media sits on the Post's Text. Raises `NotFoundError` when it isn't there."""
    placed = next((p for p in post.text_media if p.media_id == media_id), None)
    if placed is None:
        raise NotFoundError("This post's text has no such media.")
    return placed


def remove_from_text(post: Post, placed: TextMedia) -> None:
    """Take the Media off the Text. The record and its file stay until nothing references them."""
    post.text_media.remove(placed)


async def get_user_media(db: AsyncSession, *, user_id: str, media_id: str) -> Optional[Media]:
    """The User's Media, or None when it isn't theirs."""
    result = await db.execute(select(Media).where(Media.id == media_id, Media.user_id == user_id))
    return result.scalar_one_or_none()
