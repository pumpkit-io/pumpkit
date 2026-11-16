import asyncio
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpkit.auth.models import User
from pumpkit.auth.service import users
from pumpkit.authors import service as authors_service
from pumpkit.authors.x_reader import XReader, XReaderError
from pumpkit.core.background import TaskRegistry
from pumpkit.core.config import settings
from pumpkit.core.llm import LLM, LLMError
from pumpkit.core.llm_client import LLMNotConfiguredError
from pumpkit.core.logging import logger
from pumpkit.core.time import Clock, as_utc
from pumpkit.positioning import service
from pumpkit.positioning.draft import (
    DRAFT_CALL_SECONDS,
    DRAFT_MAX_TOKENS,
    DRAFT_SLOT_WAIT_SECONDS,
    DRAFT_WINDOW,
    DRAFTS_PER_DAY,
    PositioningDraft,
    XProfile,
    draft_messages,
    draft_text,
    post_texts,
)
from pumpkit.positioning.models import Positioning, PositioningDraftRecord
from pumpkit.positioning.schemas import (
    PositioningDraftResponse,
    PositioningPageResponse,
    PositioningResponse,
)
from pumpkit.x_connection import service as x_connection_service

_WRITE_IT_YOURSELF = "Write it yourself."
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
    # The lock `start_draft` holds, so a save never lands between its check and its draft.
    await users.require_locked_user(db, user_id=user.id, clock=lambda: now)
    positioning = await service.save_positioning(db, user_id=user.id, text=text, now=now)
    await db.commit()
    return _response(positioning)


async def get_positioning_page(
    db: AsyncSession, user: User, now: datetime
) -> PositioningPageResponse:
    positioning = await service.get_positioning(db, user_id=user.id)
    if positioning is not None:
        return PositioningPageResponse(**_response(positioning).model_dump(), draft=None)
    draft = await service.get_draft(db, user_id=user.id)
    return PositioningPageResponse(text=None, saved_at=None, draft=_draft_response(draft, now))


def _draft_response(
    draft: Optional[PositioningDraftRecord], now: datetime
) -> Optional[PositioningDraftResponse]:
    if draft is None:
        return None
    if service.is_stale(draft, now=now):
        return PositioningDraftResponse(state="failed", text=None, reason=_NOT_DRAFTED)
    return PositioningDraftResponse(state=draft.state, text=draft.text, reason=draft.reason)


@dataclass(frozen=True)
class _DraftRun:
    """What a draft reads, read before the request that starts it answers."""

    user_id: str
    x_user_id: str
    profile: XProfile
    # The draft's `started_at`: a later start replaces it, and this run records nothing.
    started_at: datetime


async def start_draft(
    db: AsyncSession,
    reader: XReader,
    llm: LLM,
    tasks: TaskRegistry,
    sessions: async_sessionmaker[AsyncSession],
    user: User,
    clock: Clock,
) -> None:
    """
    Start drafting the User's Positioning in the background (ADR 0030), unless they have a
    Positioning, or a draft that is running or ready. A start that can't read X or ask the model,
    or finds today's draft requests used up, runs nothing and leaves a draft that failed.
    """
    # Serializes a User's starts, so two tabs start one draft and can't both take the last request.
    if await users.lock_user_id(db, user_id=user.id) is None:
        return
    now = clock()
    if await service.get_positioning(db, user_id=user.id) is not None:
        return
    draft = await service.get_draft(db, user_id=user.id)
    if draft is not None and draft.state != "failed" and not service.is_stale(draft, now=now):
        return
    connection = await x_connection_service.get_connection(db, user_id=user.id)
    counted_since = now - DRAFT_WINDOW
    # Checked before X is read: without both providers a request would be paid for and wasted.
    if connection is None or not reader.is_configured():
        await _leave_failed(db, user_id=user.id, reason=_X_NOT_READ, now=now)
        return
    used = await service.draft_requests_since(db, user_id=user.id, since=counted_since)
    if not llm.is_configured() or len(used) >= DRAFTS_PER_DAY:
        await _leave_failed(db, user_id=user.id, reason=_NOT_DRAFTED, now=now)
        return
    await service.log_draft_request(db, user_id=user.id, now=now, counted_since=counted_since)
    await service.start_draft(db, user_id=user.id, now=now)
    run = _DraftRun(
        user_id=user.id,
        x_user_id=connection.x_user_id,
        profile=XProfile(
            handle=connection.handle,
            bio=connection.bio,
            location=connection.location,
            website=connection.website,
        ),
        started_at=now,
    )
    # Before the task starts, so its own session finds the running draft and the lock is freed.
    await db.commit()
    await tasks.start(_task_name(user.id), _run_draft(run, reader, llm, sessions, clock))


async def _leave_failed(db: AsyncSession, *, user_id: str, reason: str, now: datetime) -> None:
    """Leave the User a draft that failed for `reason`, in place of an older failure's."""
    await service.fail_draft(db, user_id=user_id, reason=reason, now=now)
    await db.commit()


def _task_name(user_id: str) -> str:
    return f"draft the positioning of {user_id}"


async def _run_draft(
    run: _DraftRun,
    reader: XReader,
    llm: LLM,
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
) -> None:
    """The background task: X and the model with no session open, then the outcome in its own."""
    try:
        text, reason = await _draft(run, reader, llm)
    except asyncio.CancelledError:
        # Cancelled on shutdown: fail it now rather than leave it running until it goes stale.
        try:
            await _finish_draft(run, None, _NOT_DRAFTED, sessions, clock)
        except Exception:
            logger.exception("Couldn't record a cancelled positioning draft as failed")
        raise
    except Exception:
        await _finish_draft(run, None, _NOT_DRAFTED, sessions, clock)
        raise
    await _finish_draft(run, text, reason, sessions, clock)


async def _finish_draft(
    run: _DraftRun,
    text: Optional[str],
    reason: Optional[str],
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
) -> None:
    async with sessions() as db:
        await service.finish_draft(
            db,
            user_id=run.user_id,
            started_at=run.started_at,
            text=text,
            reason=reason,
            now=clock(),
        )
        await db.commit()


async def _draft(run: _DraftRun, reader: XReader, llm: LLM) -> tuple[Optional[str], Optional[str]]:
    """
    A draft of the User's Positioning from their X profile and newest posts, or no draft and the
    reason. A failed X read or model call is a reason, not an error.
    """
    profile = run.profile
    try:
        # By X ID: the stored handle is as old as the last sign-in, and may now be someone else's.
        newest = await authors_service.newest_posts(reader, x_user_id=run.x_user_id)
    except XReaderError as error:
        logger.warning(
            "Reading X account %s's posts for a positioning draft failed: %s", run.x_user_id, error
        )
        return None, _X_NOT_READ
    if newest.handle is not None:
        profile = replace(profile, handle=newest.handle)
    posts = post_texts([post.text for post in newest.posts])
    if profile.is_blank() and not posts:
        return None, _NOTHING_TO_DRAFT_FROM
    try:
        # The call's own timeout starts once it holds a slot, so this also bounds the wait for one.
        async with asyncio.timeout(DRAFT_SLOT_WAIT_SECONDS + DRAFT_CALL_SECONDS):
            result = await llm.structured(
                model=settings.LLM_POSITIONING_MODEL,
                messages=draft_messages(profile, posts),
                response_model=PositioningDraft,
                max_tokens=DRAFT_MAX_TOKENS,
                timeout_seconds=DRAFT_CALL_SECONDS,
            )
    except TimeoutError:
        logger.warning("Drafting a positioning failed: no model slot came free in time to answer")
        return None, _NOT_DRAFTED
    except (LLMError, LLMNotConfiguredError) as error:
        logger.warning("Drafting a positioning failed: %s", error or type(error).__name__)
        return None, _NOT_DRAFTED
    text = draft_text(result.parsed)
    return text, None if text is not None else _NOT_DRAFTED
