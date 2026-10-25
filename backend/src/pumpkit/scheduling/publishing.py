"""
Publishing a Scheduled post on X, for Post now and the publisher (ADR 0007). Owns every commit
of a publish: the claim and any rotated tokens are committed before X is called.
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.x_connection.service as x_connections_service
from pumpkit.scheduling import publish, service
from pumpkit.scheduling.models import ScheduledPost
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


async def fail_stuck(db: AsyncSession, *, now: datetime) -> None:
    scheduled_post_ids = await publish.fail_stuck(db, now=now)
    await db.commit()
    for scheduled_post_id in scheduled_post_ids:
        scheduled_post = await service.get(db, scheduled_post_id=scheduled_post_id)
        if scheduled_post is not None:
            publish.capture_failed(scheduled_post, "outcome_unknown")


async def _publish_claimed(
    db: AsyncSession, publisher: XPublisher, *, scheduled_post_id: str, now: datetime
) -> None:
    scheduled_post = await service.get(db, scheduled_post_id=scheduled_post_id)
    assert scheduled_post is not None

    try:
        await _publish(db, publisher, scheduled_post, now=now)
    except publish.Failed as failed:
        failed_for_good = await publish.record_failure(db, scheduled_post, failed, now=now)
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
                    await x_connections_service.flag_needs_reconnect(db, connection, now=now)
                raise
            await service.record_part_live(db, part, x_post_id=x_post_id)
            # Commit before the next Part, so a crash leaves a true record of what is live.
            await db.commit()
        reply_to = part.x_post_id
