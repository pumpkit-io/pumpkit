"""
Publishing a Scheduled post on X, for Post now and the publisher (ADR 0007). Owns every commit
of a publish: the claim and any rotated tokens are committed before X is called.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.users as users_service
import pumpkit.x_connection.service as x_connections_service
from pumpkit.core.time import as_utc
from pumpkit.scheduling import publish, service
from pumpkit.scheduling.models import ScheduledPost
from pumpkit.scheduling.top_up_charges import rebalance_top_ups
from pumpkit.x_connection.x_publisher import XPublisher


async def publish_scheduled_post(
    db: AsyncSession, publisher: XPublisher, *, scheduled_post_id: str, now: datetime
) -> bool:
    """Post now. False when it wasn't scheduled, for instance because another caller claimed it."""
    claimed = await service.claim(db, scheduled_post_id=scheduled_post_id, now=now)
    # Commit the claim before calling X: from here on, no other caller can publish it.
    await db.commit()
    if not claimed:
        return False
    await _publish_claimed(db, publisher, scheduled_post_id=scheduled_post_id, now=now)
    return True


async def publish_next_due(db: AsyncSession, publisher: XPublisher, *, now: datetime) -> bool:
    """The publisher's step. False when nothing is due."""
    scheduled_post_id = await service.claim_next_due(db, now=now)
    # Commit the claim before calling X: from here on, no other pass can publish it.
    await db.commit()
    if scheduled_post_id is None:
        return False
    await _publish_claimed(db, publisher, scheduled_post_id=scheduled_post_id, now=now)
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


async def _publish_claimed(
    db: AsyncSession, publisher: XPublisher, *, scheduled_post_id: str, now: datetime
) -> None:
    scheduled_post = await service.get(db, scheduled_post_id=scheduled_post_id)
    assert scheduled_post is not None

    try:
        await _publish(db, publisher, scheduled_post, now=now)
    except publish.Failed as failed:
        # Still held when the failure came before the call to X; taken again after one.
        await users_service.lock_user_id(db, user_id=scheduled_post.user_id)
        failed_for_good = await publish.record_failure(db, scheduled_post, failed, now=now)
        if failed_for_good:
            await rebalance_top_ups(
                db, user_id=scheduled_post.user_id, moments=[as_utc(scheduled_post.publish_at)]
            )
        await db.commit()
        if failed_for_good:
            publish.capture_failed(scheduled_post, failed.category)
        return

    await service.record_published(db, scheduled_post, now=now)
    await db.commit()
    publish.capture_published(scheduled_post)


async def _publish(
    db: AsyncSession, publisher: XPublisher, scheduled_post: ScheduledPost, *, now: datetime
) -> None:
    """
    Every Part not yet live, in order, each as a reply to the one before (ADR 0014), or
    `publish.Failed`. The caller commits whatever it flushed, either way.
    """
    # One lock order everywhere, User then X connection then Scheduled post, so no two deadlock.
    await users_service.lock_user_id(db, user_id=scheduled_post.user_id)
    connection = await publish.connection_to_publish_on(db, scheduled_post)
    access_token = await publish.fresh_access_token(db, publisher, connection, now=now)
    # Commit the rotated tokens, or end the read, before the call to X: it releases the lock.
    await db.commit()

    reply_to = None
    for part in scheduled_post.parts:
        if part.x_post_id is None:
            try:
                x_post_id = await publish.call_x(
                    publisher, scheduled_post, part, reply_to=reply_to, access_token=access_token
                )
            except publish.Failed as failed:
                if failed.category == "reconnect_needed":
                    await users_service.lock_user_id(db, user_id=scheduled_post.user_id)
                    await x_connections_service.flag_needs_reconnect(db, connection, now=now)
                raise
            await service.record_part_live(db, part, x_post_id=x_post_id)
            # Commit before the next Part, so a crash leaves a true record of what is live.
            await db.commit()
        reply_to = part.x_post_id
