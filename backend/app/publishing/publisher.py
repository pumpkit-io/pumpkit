"""
The publisher (ADR 0007): a process of its own that publishes due Scheduled posts.

`run_pass` is one sweep: it fails Scheduled posts a crashed publisher left in publishing,
then claims and publishes due ones one at a time until none is left. `run` repeats it every
poll interval until asked to stop. Run it with `python -m app.publishing`.
"""

import asyncio
from datetime import timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.api.services.scheduled_posts as scheduled_posts_service
from app.core.clock import Clock
from app.core.logger import logger
from app.core.posthog import posthog_client
from app.core.x_publisher import XPublisher
from app.publishing.publish import OUTCOME_UNKNOWN_REASON, publish_claimed

# Far longer than one call to X takes: a Scheduled post publishing this long lost its publisher.
STUCK_AFTER = timedelta(minutes=10)


async def run_pass(
    session_maker: async_sessionmaker[AsyncSession],
    publisher: XPublisher,
    clock: Clock,
    stop: Optional[asyncio.Event] = None,
) -> None:
    """One sweep. With `stop` set, it returns after the Scheduled post in hand."""
    async with session_maker() as db:
        now = clock()
        user_ids = await scheduled_posts_service.fail_stuck(
            db, publishing_since=now - STUCK_AFTER, reason=OUTCOME_UNKNOWN_REASON, now=now
        )
        await db.commit()
    for user_id in user_ids:
        posthog_client.capture(
            "scheduled_post_failed", distinct_id=user_id, properties={"reason": "outcome_unknown"}
        )

    while stop is None or not stop.is_set():
        # A session per Scheduled post: publishing commits as it goes.
        async with session_maker() as db:
            now = clock()
            scheduled_post_id = await scheduled_posts_service.claim_next_due(db, now=now)
            # Commit the claim before calling X: from here on, no other pass can publish it.
            await db.commit()
            if scheduled_post_id is None:
                return
            await publish_claimed(
                db,
                publisher,
                scheduled_post_id=scheduled_post_id,
                now=now,
            )


async def run(
    session_maker: async_sessionmaker[AsyncSession],
    publisher: XPublisher,
    clock: Clock,
    *,
    poll_interval: timedelta,
    stop: asyncio.Event,
) -> None:
    """Run a pass every `poll_interval` until `stop` is set. A failed pass is logged and retried."""
    while not stop.is_set():
        try:
            await run_pass(session_maker, publisher, clock, stop)
        except Exception:
            logger.exception("Publisher pass failed; trying again next interval")
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_interval.total_seconds())
        except TimeoutError:
            pass
