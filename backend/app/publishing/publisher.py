"""The publisher (ADR 0007): a process of its own. Run it with `python -m app.publishing`."""

import asyncio
from datetime import timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.core.logger import logger
from app.core.x_publisher import XPublisher
from app.publishing.publish import fail_stuck, publish_next_due


async def run_pass(
    session_maker: async_sessionmaker[AsyncSession],
    publisher: XPublisher,
    clock: Clock,
    stop: Optional[asyncio.Event] = None,
) -> None:
    """Publish every due Scheduled post. With `stop` set, it returns after the one in hand."""
    async with session_maker() as db:
        await fail_stuck(db, now=clock())
    while stop is None or not stop.is_set():
        # A session per Scheduled post: publishing commits as it goes.
        async with session_maker() as db:
            if not await publish_next_due(db, publisher, now=clock()):
                return


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
