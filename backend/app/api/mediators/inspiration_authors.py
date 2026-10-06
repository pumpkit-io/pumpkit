from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.author_posts as author_posts_service
import app.api.services.inspiration_authors as inspiration_authors_service
from app.core.x_reader import HandleNotFoundError, XReader
from app.db.models import User
from app.schemas.inspiration_authors import InspirationAuthorResponse

MAX_INSPIRATION_AUTHORS = 3


def _already_listed(handle: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"@{handle} is already one of your Inspiration authors.",
    )


async def add_author(
    db: AsyncSession, reader: XReader, user: User, handle: str, now: datetime
) -> InspirationAuthorResponse:
    """
    Fetch `handle`'s recent posts, store the new ones and add the handle to the User's list.

    The list checks run first so a duplicate or a fourth author costs no twitterapi.io call.
    A 404 for a handle X doesn't know and a 422 for one without original posts store nothing.
    """
    user_id = user.id
    if await inspiration_authors_service.get_author(db, user_id=user_id, handle=handle):
        raise _already_listed(handle)
    if await inspiration_authors_service.count_authors(db, user_id=user_id) >= (
        MAX_INSPIRATION_AUTHORS
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You can have up to {MAX_INSPIRATION_AUTHORS} Inspiration authors. "
            "Remove one to add another.",
        )

    try:
        posts = await reader.fetch_recent_posts(handle)
    except HandleNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"@{handle} doesn't exist on X."
        )
    if not posts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"@{handle} has no original posts to learn from.",
        )

    await author_posts_service.store_new_posts(db, handle=handle, posts=posts, now=now)
    await author_posts_service.record_fetch(db, handle=handle, now=now)
    try:
        await inspiration_authors_service.add_author(db, user_id=user_id, handle=handle, now=now)
        await db.commit()
    except IntegrityError:
        # A concurrent add of the same handle won the unique (user_id, handle) constraint.
        raise _already_listed(handle)

    summaries = await inspiration_authors_service.list_authors(db, user_id=user_id)
    added = next(summary for summary in summaries if summary.handle == handle)
    return InspirationAuthorResponse(
        handle=added.handle, last_fetched_at=added.last_fetched_at, post_count=added.post_count
    )
