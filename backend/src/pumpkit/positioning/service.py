from datetime import datetime
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.core.time import as_utc
from pumpkit.positioning.draft import DRAFT_STALE_AFTER
from pumpkit.positioning.models import (
    DraftState,
    Positioning,
    PositioningDraftRecord,
    PositioningDraftRequest,
)


async def get_positioning(db: AsyncSession, *, user_id: str) -> Optional[Positioning]:
    return await db.get(Positioning, user_id)


async def save_positioning(
    db: AsyncSession, *, user_id: str, text: str, now: datetime
) -> Positioning:
    """Make `text` the User's Positioning, in place of any they had, and drop their draft. Flushes."""
    await db.execute(
        delete(PositioningDraftRecord).where(PositioningDraftRecord.user_id == user_id)
    )
    positioning = await db.get(Positioning, user_id)
    if positioning is None:
        try:
            async with db.begin_nested():
                positioning = Positioning(user_id=user_id, text=text, saved_at=now)
                db.add(positioning)
            return positioning
        except IntegrityError:
            # A concurrent first save inserted the row; this one overwrites it.
            positioning = await db.get(Positioning, user_id, populate_existing=True)
            if positioning is None:
                raise
    positioning.text = text
    positioning.saved_at = now
    await db.flush()
    return positioning


async def draft_requests_since(
    db: AsyncSession, *, user_id: str, since: datetime
) -> list[datetime]:
    """When the User made each draft request after `since`, oldest first."""
    query = (
        select(PositioningDraftRequest.requested_at)
        .where(
            PositioningDraftRequest.user_id == user_id,
            PositioningDraftRequest.requested_at > since,
        )
        .order_by(PositioningDraftRequest.requested_at)
    )
    return [as_utc(requested_at) for requested_at in (await db.execute(query)).scalars()]


async def log_draft_request(
    db: AsyncSession, *, user_id: str, now: datetime, counted_since: datetime
) -> None:
    """
    Record one draft request that goes on to read X, and drop the User's requests the limit
    no longer counts: those made at or before `counted_since`. Flushes.
    """
    await db.execute(
        delete(PositioningDraftRequest).where(
            PositioningDraftRequest.user_id == user_id,
            PositioningDraftRequest.requested_at <= counted_since,
        )
    )
    db.add(PositioningDraftRequest(user_id=user_id, requested_at=now))
    await db.flush()


async def get_draft(db: AsyncSession, *, user_id: str) -> Optional[PositioningDraftRecord]:
    return await db.get(PositioningDraftRecord, user_id, populate_existing=True)


async def start_draft(db: AsyncSession, *, user_id: str, now: datetime) -> None:
    """Make the User's draft a running one started at `now`, in place of any they had. Flushes."""
    await _set_draft(db, user_id=user_id, state="running", text=None, reason=None, started_at=now)


async def fail_draft(db: AsyncSession, *, user_id: str, reason: str, now: datetime) -> None:
    """Make the User's draft one that failed for `reason`, with no draft run. Flushes."""
    await _set_draft(db, user_id=user_id, state="failed", text=None, reason=reason, started_at=now)


async def finish_draft(
    db: AsyncSession,
    *,
    user_id: str,
    started_at: datetime,
    text: Optional[str],
    reason: Optional[str],
    now: datetime,
) -> None:
    """
    End the draft started at `started_at` with its `text`, or else `reason`, unless the User saved
    a Positioning, another draft started since, or it already reads as failed for running too long.
    Flushes.
    """
    draft = await db.get(PositioningDraftRecord, user_id, with_for_update=True)
    if (
        draft is None
        or draft.state != "running"
        or as_utc(draft.started_at) != as_utc(started_at)
        or is_stale(draft, now=now)
    ):
        return
    draft.state = "ready" if text is not None else "failed"
    draft.text = text
    draft.reason = None if text is not None else reason
    await db.flush()


async def _set_draft(
    db: AsyncSession,
    *,
    user_id: str,
    state: DraftState,
    text: Optional[str],
    reason: Optional[str],
    started_at: datetime,
) -> None:
    draft = await db.get(PositioningDraftRecord, user_id)
    if draft is None:
        draft = PositioningDraftRecord(user_id=user_id)
        db.add(draft)
    draft.state = state
    draft.text = text
    draft.reason = reason
    draft.started_at = started_at
    await db.flush()


def is_stale(draft: PositioningDraftRecord, *, now: datetime) -> bool:
    """True for a draft still running past when its calls must have ended: a restart lost it."""
    return draft.state == "running" and now - as_utc(draft.started_at) >= DRAFT_STALE_AFTER
