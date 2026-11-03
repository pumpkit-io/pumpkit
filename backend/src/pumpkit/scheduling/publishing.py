"""
Publishing a Scheduled post on X, for Post now and the publisher (ADR 0007). Owns every commit
of a publish: the claim and any rotated tokens are committed before X is called.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.users as users_service
import pumpkit.x_connection.service as x_connections_service
from pumpkit.core.logging import logger
from pumpkit.core.storage import FileStorage
from pumpkit.core.time import Clock, as_utc
from pumpkit.scheduling import publish, service
from pumpkit.scheduling.models import ScheduledPost
from pumpkit.scheduling.top_up_charges import rebalance_top_ups
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


async def publish_next_due(
    db: AsyncSession, publisher: XPublisher, storage: FileStorage, *, clock: Clock
) -> bool:
    """The publisher's step. False when nothing is due."""
    now = clock()
    scheduled_post_id = await service.claim_next_due(db, now=now)
    # Commit the claim before calling X: from here on, no other pass can publish it.
    await db.commit()
    if scheduled_post_id is None:
        return False
    await _publish_claimed(
        db, publisher, storage, scheduled_post_id=scheduled_post_id, now=now, clock=clock
    )
    return True


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


async def _publish_claimed(
    db: AsyncSession,
    publisher: XPublisher,
    storage: FileStorage,
    *,
    scheduled_post_id: str,
    now: datetime,
    clock: Clock,
) -> None:
    scheduled_post = await service.get_existing(db, scheduled_post_id=scheduled_post_id)
    claim = _Claim(scheduled_post=scheduled_post, held_since=now, clock=clock)
    try:
        await _settle(db, publisher, storage, claim, now=now)
    except _ClaimLost:
        await db.commit()
        logger.warning(
            "Scheduled post %s was settled by recovery while publishing; left as it is",
            scheduled_post_id,
        )


async def _settle(
    db: AsyncSession, publisher: XPublisher, storage: FileStorage, claim: _Claim, *, now: datetime
) -> None:
    scheduled_post = claim.scheduled_post
    try:
        await _publish(db, publisher, storage, claim, now=now)
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
) -> None:
    """
    Every Part not yet live, in order, each with its Media uploaded just before it and as a reply
    to the one before (ADR 0014), or `publish.Failed`. The caller commits whatever it flushed.
    """
    scheduled_post = claim.scheduled_post
    # One lock order everywhere, User then X connection then Scheduled post, so no two deadlock.
    await users_service.lock_user_id(db, user_id=scheduled_post.user_id)
    connection = await publish.connection_to_publish_on(db, scheduled_post)
    access_token = await publish.fresh_access_token(db, publisher, connection, now=now)
    # Commit the rotated tokens, or end the read, before the call to X: it releases the lock.
    await db.commit()

    reply_to = None
    for part, media in zip(scheduled_post.parts, service.media_by_part(scheduled_post)):
        if part.x_post_id is None:
            try:
                media_ids = []
                for one in media:
                    await claim.renew(db)
                    x_media_id = await publish.upload_media(
                        publisher, storage, scheduled_post, part, one, access_token=access_token
                    )
                    if one.alt_text is not None:
                        await claim.renew(db)
                        await publish.set_alt_text(
                            publisher,
                            scheduled_post,
                            part,
                            one,
                            x_media_id=x_media_id,
                            access_token=access_token,
                        )
                    media_ids.append(x_media_id)
                await claim.renew(db)
                x_post_id = await publish.call_x(
                    publisher,
                    scheduled_post,
                    part,
                    reply_to=reply_to,
                    access_token=access_token,
                    media_ids=media_ids,
                )
            except publish.Failed as failed:
                if failed.category == "reconnect_needed":
                    await users_service.lock_user_id(db, user_id=scheduled_post.user_id)
                    await x_connections_service.flag_needs_reconnect(
                        db, connection, now=claim.clock()
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
            await service.record_part_live(db, part, x_post_id=x_post_id)
            # Commit before the next Part, so a crash leaves a true record of what is live.
            await db.commit()
            # The next renewal or outcome commits the deleted files; a failed delete is only logged.
            await publish.delete_published_files(storage, media)
        reply_to = part.x_post_id
