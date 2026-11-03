"""
One-time upload links: a random token in the URL, stored only as its hash beside the User, Post
and Part it was made for, so a link can't be altered to name another, and spent by the first
upload that starts through it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, cast

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.core.errors import GoneError, NotFoundError
from pumpkit.core.security import generate_token, hash_token
from pumpkit.core.time import as_utc
from pumpkit.posts.models import MediaUploadLink

LIFETIME = timedelta(minutes=15)
# Kept this long past expiry, so a late upload is told the link expired rather than unknown.
_KEPT_AFTER_EXPIRY = timedelta(days=1)
_NEW_LINK = "Call attach_media again for a new one."


@dataclass(frozen=True)
class NewUploadLink:
    token: str
    expires_at: datetime


async def create(
    db: AsyncSession,
    *,
    user_id: str,
    post_id: str,
    part_index: int,
    alt_text: Optional[str],
    app_connection_id: str,
    now: datetime,
) -> NewUploadLink:
    """Store a new link for the Part, for the app connection that asked for it. Flushes."""
    link = NewUploadLink(token=generate_token(32), expires_at=now + LIFETIME)
    db.add(
        MediaUploadLink(
            token_hash=hash_token(link.token),
            user_id=user_id,
            post_id=post_id,
            part_index=part_index,
            alt_text=alt_text,
            app_connection_id=app_connection_id,
            created_at=now,
            expires_at=link.expires_at,
        )
    )
    await db.flush()
    return link


def _used() -> GoneError:
    return GoneError(f"This upload link was used already. {_NEW_LINK}", code="UPLOAD_LINK_USED")


async def find_usable(db: AsyncSession, *, token: str, now: datetime) -> MediaUploadLink:
    """The link for `token`, refused when unknown, used or expired."""
    link = (
        await db.execute(
            select(MediaUploadLink).where(MediaUploadLink.token_hash == hash_token(token))
        )
    ).scalar_one_or_none()
    if link is None:
        raise NotFoundError(
            f"This isn't a Pumpkit upload link. {_NEW_LINK}", code="UPLOAD_LINK_UNKNOWN"
        )
    if link.used_at is not None:
        raise _used()
    if as_utc(link.expires_at) <= now:
        raise GoneError(f"This upload link expired. {_NEW_LINK}", code="UPLOAD_LINK_EXPIRED")
    return link


async def spend(db: AsyncSession, *, link: MediaUploadLink, now: datetime) -> None:
    """
    Mark the link used, or refuse it if another upload spent it since it was read: the update's
    condition decides between two at once. Flushes.
    """
    spent = await db.execute(
        update(MediaUploadLink)
        .where(MediaUploadLink.token_hash == link.token_hash, MediaUploadLink.used_at.is_(None))
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult, spent).rowcount != 1:
        raise _used()


async def delete_expired(db: AsyncSession, *, now: datetime) -> None:
    """Delete links expired more than a day before `now`. Flushes."""
    await db.execute(
        delete(MediaUploadLink).where(MediaUploadLink.expires_at <= now - _KEPT_AFTER_EXPIRY)
    )
