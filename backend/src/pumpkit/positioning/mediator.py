from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.auth.service import users
from pumpkit.authors import service as authors_service
from pumpkit.authors.x_reader import XReader, XReaderError
from pumpkit.core.config import settings
from pumpkit.core.errors import RetryLaterError
from pumpkit.core.llm import LLM, LLMError
from pumpkit.core.llm_client import LLMNotConfiguredError
from pumpkit.core.logging import logger
from pumpkit.core.time import as_utc
from pumpkit.positioning import service
from pumpkit.positioning.draft import (
    DRAFT_WINDOW,
    DRAFTS_PER_DAY,
    PositioningDraft,
    XProfile,
    draft_messages,
    draft_text,
    post_texts,
)
from pumpkit.positioning.models import Positioning
from pumpkit.positioning.schemas import (
    PositioningDraftResponse,
    PositioningPageResponse,
    PositioningResponse,
)
from pumpkit.x_connection import service as x_connection_service

_WRITE_IT_YOURSELF = "Write it yourself, a few sentences is enough."
_X_NOT_READ = f"We couldn't read your X profile. {_WRITE_IT_YOURSELF}"
_NOTHING_TO_DRAFT_FROM = f"Your X profile has nothing to draft from yet. {_WRITE_IT_YOURSELF}"
_NOT_DRAFTED = f"We couldn't draft your positioning. {_WRITE_IT_YOURSELF}"


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


async def get_positioning_page(
    db: AsyncSession, user: User, now: datetime
) -> PositioningPageResponse:
    positioning = _response(await service.get_positioning(db, user_id=user.id))
    used = await service.count_draft_requests(db, user_id=user.id, since=now - DRAFT_WINDOW)
    return PositioningPageResponse(
        **positioning.model_dump(), can_draft=used.count < DRAFTS_PER_DAY
    )


async def draft_positioning(
    db: AsyncSession, reader: XReader, llm: LLM, user: User, now: datetime
) -> PositioningDraftResponse:
    """
    Draft the User's Positioning from their X profile and newest posts, saving no Positioning.
    A failed X read or model call answers with no draft and the reason, not an error.
    """
    # Serializes a User's requests, so two at once can't both take the last draft of the day.
    await users.lock_user_id(db, user_id=user.id)
    used = await service.count_draft_requests(db, user_id=user.id, since=now - DRAFT_WINDOW)
    if used.count >= DRAFTS_PER_DAY and used.oldest is not None:
        raise RetryLaterError(
            "You can draft again tomorrow.", retry_at=used.oldest + DRAFT_WINDOW, now=now
        )
    connection = await x_connection_service.get_connection(db, user_id=user.id)
    if connection is None:
        return PositioningDraftResponse(text=None, reason=_X_NOT_READ, can_draft=True)
    profile = XProfile(
        handle=connection.handle,
        bio=connection.bio,
        location=connection.location,
        website=connection.website,
    )
    await service.log_draft_request(db, user_id=user.id, now=now)
    # Early commit: reading X is paid for whatever comes of it, and the lock ends before the calls.
    await db.commit()

    def answer(text: Optional[str], reason: Optional[str]) -> PositioningDraftResponse:
        return PositioningDraftResponse(
            text=text, reason=reason, can_draft=used.count + 1 < DRAFTS_PER_DAY
        )

    try:
        newest = await authors_service.newest_posts(reader, handle=profile.handle)
    except XReaderError as error:
        logger.warning(
            "Reading @%s's posts for a positioning draft failed: %s", profile.handle, error
        )
        return answer(None, _X_NOT_READ)
    posts = post_texts([post.text for post in newest])
    if profile.is_blank() and not posts:
        return answer(None, _NOTHING_TO_DRAFT_FROM)
    try:
        result = await llm.structured(
            model=settings.LLM_POSITIONING_MODEL,
            messages=draft_messages(profile, posts),
            response_model=PositioningDraft,
        )
    except (LLMError, LLMNotConfiguredError) as error:
        logger.warning("Drafting a positioning failed: %s", error)
        return answer(None, _NOT_DRAFTED)
    text = draft_text(result.parsed)
    return answer(text, None if text is not None else _NOT_DRAFTED)
