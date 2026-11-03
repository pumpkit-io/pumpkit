"""
Publishing a Scheduled post on X, for Post now and the publisher (ADR 0007). Owns every commit
of a publish: the claim and any rotated tokens are committed before X is called.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.users as users_service
import pumpkit.x_connection.service as x_connections_service
from pumpkit.core.logging import logger
from pumpkit.core.storage import FileStorage
from pumpkit.core.time import Clock, as_utc
from pumpkit.posts.models import MEDIA_VIDEO
from pumpkit.scheduling import publish, service
from pumpkit.scheduling.models import ScheduledPost
from pumpkit.scheduling.top_up_charges import rebalance_top_ups
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_publisher import XPublisher


async def publish_scheduled_post(
    db: AsyncSession,
    publisher: XPublisher,
    storage: FileStorage,
    *,
    scheduled_post_id: str,
    now: datetime,
    clock: Clock,
) -> bool:
    """
    Post now, claimed and recorded at `now`, its claim renewed by `clock`. False when it wasn't
    scheduled, for instance because another caller claimed it.
    """
    claimed = await service.claim(db, scheduled_post_id=scheduled_post_id, now=now)
    # Commit the claim before calling X: from here on, no other caller can publish it.
    await db.commit()
    if not claimed:
        return False
    await _publish_claimed(
        db, publisher, storage, scheduled_post_id=scheduled_post_id, now=now, clock=clock
    )
    return True


async def claim_next_due(db: AsyncSession, *, now: datetime) -> Optional[str]:
    """The publisher's claim of the soonest due Scheduled post, committed; None when none is due."""
    scheduled_post_id = await service.claim_next_due(db, now=now)
    # Commit the claim before calling X: from here on, no other pass can publish it.
    await db.commit()
    return scheduled_post_id


async def publish_claimed(
    db: AsyncSession,
    publisher: XPublisher,
    storage: FileStorage,
    *,
    scheduled_post_id: str,
    claimed_at: datetime,
    clock: Clock,
    stop: Optional[asyncio.Event] = None,
) -> None:
    """
    Publish what `claim_next_due` claimed at `claimed_at`, its claim renewed by `clock`. Once
    `stop` is set, it starts no more calls to X and hands back the Parts not yet live.
    """
    await _publish_claimed(
        db,
        publisher,
        storage,
        scheduled_post_id=scheduled_post_id,
        now=claimed_at,
        clock=clock,
        stop=stop,
    )


async def recover_stuck(db: AsyncSession, *, now: datetime) -> None:
    publishing_since = now - publish.STUCK_AFTER
    user_ids = await service.stuck_user_ids(db, publishing_since=publishing_since)
    if not user_ids:
        await db.commit()
        return
    # Users before Scheduled post rows, as requests lock them, in id order so two passes agree.
    for user_id in user_ids:
        await users_service.lock_user_id(db, user_id=user_id)
    recovered = await publish.recover_stuck(
        db, publishing_since=publishing_since, user_ids=user_ids, now=now
    )
    for scheduled_post in recovered.failed:
        await rebalance_top_ups(
            db, user_id=scheduled_post.user_id, moments=[as_utc(scheduled_post.publish_at)]
        )
    await db.commit()
    for scheduled_post in recovered.published:
        publish.capture_published(scheduled_post)
    for scheduled_post in recovered.failed:
        publish.capture_failed(scheduled_post, "outcome_unknown")


class _ClaimLost(Exception):
    pass


class _Stopped(Exception):
    pass


@dataclass
class _Claim:
    """
    A publish's hold on its Scheduled post, renewed before each call to X so `recover_stuck`
    leaves a long publish alone. Once lost, the publish writes nothing more.
    """

    scheduled_post: ScheduledPost
    held_since: datetime
    clock: Clock

    async def renew(self, db: AsyncSession) -> None:
        """Commits, as the renewal must be seen before the call to X it covers."""
        renewed_at = self.clock()
        held = await service.renew_claim(
            db,
            scheduled_post_id=self.scheduled_post.id,
            held_since=self.held_since,
            now=renewed_at,
        )
        await db.commit()
        if not held:
            raise _ClaimLost()
        self.held_since = renewed_at

    async def check(self, db: AsyncSession) -> None:
        """Locks the User as recovery does, so the claim holds until the next commit."""
        await users_service.lock_user_id(db, user_id=self.scheduled_post.user_id)
        if not await service.holds_claim(
            db, scheduled_post_id=self.scheduled_post.id, held_since=self.held_since
        ):
            raise _ClaimLost()


@dataclass
class _Access:
    """
    The access token a publish sends to X, refreshed when near expiry before the call it is for,
    since a long video upload can outlast it.
    """

    claim: _Claim
    publisher: XPublisher
    connection: XConnection
    token: str
    stop: Optional[asyncio.Event]

    @classmethod
    async def start(
        cls,
        db: AsyncSession,
        publisher: XPublisher,
        claim: _Claim,
        *,
        now: datetime,
        stop: Optional[asyncio.Event],
    ) -> "_Access":
        """
        Flushes rotated tokens; the caller commits them before calling X. Raises `_Stopped`
        once `stop` is set, before the refresh can call X.
        """
        if stop is not None and stop.is_set():
            raise _Stopped()
        connection = await publish.connection_to_publish_on(db, claim.scheduled_post)
        token = await publish.fresh_access_token(db, publisher, connection, now=now)
        return cls(claim, publisher, connection, token, stop)

    async def for_call(self, db: AsyncSession) -> str:
        """
        Renews the claim, which commits any rotated tokens, then answers the token to send.
        Raises `_Stopped` instead once `stop` is set: X has not been called for this call yet.
        """
        if self.stop is not None and self.stop.is_set():
            raise _Stopped()
        now = self.claim.clock()
        if as_utc(self.connection.access_token_expires_at) - now <= publish.REFRESH_MARGIN:
            scheduled_post = self.claim.scheduled_post
            await users_service.lock_user_id(db, user_id=scheduled_post.user_id)
            self.connection = await publish.connection_still_publishing_on(db, scheduled_post)
            self.token = await publish.fresh_access_token(
                db, self.publisher, self.connection, now=now
            )
        await self.claim.renew(db)
        return self.token


async def _publish_claimed(
    db: AsyncSession,
    publisher: XPublisher,
    storage: FileStorage,
    *,
    scheduled_post_id: str,
    now: datetime,
    clock: Clock,
    stop: Optional[asyncio.Event] = None,
) -> None:
    scheduled_post = await service.get_existing(db, scheduled_post_id=scheduled_post_id)
    claim = _Claim(scheduled_post=scheduled_post, held_since=now, clock=clock)
    try:
        await _settle(db, publisher, storage, claim, now=now, stop=stop)
    except _ClaimLost:
        await db.commit()
        logger.warning(
            "Scheduled post %s was settled by recovery while publishing; left as it is",
            scheduled_post_id,
        )


async def _settle(
    db: AsyncSession,
    publisher: XPublisher,
    storage: FileStorage,
    claim: _Claim,
    *,
    now: datetime,
    stop: Optional[asyncio.Event],
) -> None:
    scheduled_post = claim.scheduled_post
    try:
        await _publish(db, publisher, storage, claim, now=now, stop=stop)
    except _Stopped:
        # No POST /2/tweets was in flight, so X surely holds nothing unrecorded: safe to retry.
        await claim.check(db)
        await service.release_claim(db, scheduled_post, now=claim.clock())
        await db.commit()
        logger.info("Publisher stopping: Scheduled post %s handed back", scheduled_post.id)
        return
    except publish.Failed as failed:
        await claim.check(db)
        failed_for_good = await publish.record_failure(
            db, scheduled_post, failed, now=claim.clock()
        )
        if failed_for_good:
            await rebalance_top_ups(
                db, user_id=scheduled_post.user_id, moments=[as_utc(scheduled_post.publish_at)]
            )
        await db.commit()
        if failed_for_good:
            publish.capture_failed(scheduled_post, failed.category)
        return

    await claim.check(db)
    await service.record_published(db, scheduled_post, now=claim.clock())
    await db.commit()
    publish.capture_published(scheduled_post)


async def _publish(
    db: AsyncSession,
    publisher: XPublisher,
    storage: FileStorage,
    claim: _Claim,
    *,
    now: datetime,
    stop: Optional[asyncio.Event],
) -> None:
    """
    Every Part not yet live, in order, each with its Media uploaded just before it and as a reply
    to the one before (ADR 0014), or `publish.Failed`. The caller commits whatever it flushed.
    """
    scheduled_post = claim.scheduled_post
    # One lock order everywhere, User then X connection then Scheduled post, so no two deadlock.
    await users_service.lock_user_id(db, user_id=scheduled_post.user_id)
    access = await _Access.start(db, publisher, claim, now=now, stop=stop)
    # Commit the rotated tokens, or end the read, before the call to X: it releases the lock.
    await db.commit()

    async def token_for_call() -> str:
        return await access.for_call(db)

    reply_to = None
    for part, media in zip(scheduled_post.parts, service.media_by_part(scheduled_post)):
        if part.x_post_id is None:
            try:
                media_ids = []
                for one in media:
                    x_media_id = await publish.upload_media(
                        publisher, storage, scheduled_post, part, one, token_for_call=token_for_call
                    )
                    if one.alt_text is not None and one.kind != MEDIA_VIDEO:
                        await publish.set_alt_text(
                            publisher,
                            scheduled_post,
                            part,
                            one.alt_text,
                            x_media_id=x_media_id,
                            access_token=await access.for_call(db),
                        )
                    media_ids.append(x_media_id)
                x_post_id = await publish.call_x(
                    publisher,
                    scheduled_post,
                    part,
                    reply_to=reply_to,
                    access_token=await access.for_call(db),
                    media_ids=media_ids,
                )
            except publish.Failed as failed:
                if failed.category == "reconnect_needed":
                    await users_service.lock_user_id(db, user_id=scheduled_post.user_id)
                    await x_connections_service.flag_needs_reconnect(
                        db, access.connection, now=claim.clock()
                    )
                raise
            try:
                await claim.check(db)
            except _ClaimLost:
                logger.error(
                    "X took a part of Scheduled post %s as %s after recovery settled it",
                    scheduled_post.id,
                    x_post_id,
                )
                raise
            await service.record_part_live(db, scheduled_post, part, x_post_id=x_post_id)
            # Commit before the next Part, so a crash leaves a true record of what is live.
            await db.commit()
            # The next renewal or outcome commits the deleted files; a failed delete is only logged.
            await publish.delete_published_files(storage, media)
        reply_to = part.x_post_id
