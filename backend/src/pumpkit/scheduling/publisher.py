"""The publisher (ADR 0007): a process of its own. Run it with `python -m pumpkit.scheduling.publisher`."""

import asyncio
import signal
from datetime import timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Models name `User` by string, so the process needs every model mapped, not just the ones it imports.
import pumpkit.models  # noqa: F401
from pumpkit.core.analytics import posthog_client
from pumpkit.core.config import settings
from pumpkit.core.db.session import _db_session_handler
from pumpkit.core.logging import logger
from pumpkit.core.time import Clock, system_clock
from pumpkit.scheduling.publishing import fail_stuck, publish_next_due
from pumpkit.x_connection.x_publisher import XPublisher, get_x_publisher


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
        # A session per Scheduled post: `publishing` commits as it goes.
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


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    # Finish the Scheduled post in hand, then exit: killing mid-call would leave it to recovery.
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    interval = timedelta(seconds=settings.PUBLISHER_POLL_INTERVAL_SECONDS)
    logger.info(f"Publisher started, polling every {interval.total_seconds():g}s")
    try:
        await run(
            _db_session_handler.async_session_maker,
            get_x_publisher(),
            system_clock,
            poll_interval=interval,
            stop=stop,
        )
    finally:
        logger.info("Publisher stopping")
        posthog_client.shutdown()
        await _db_session_handler.async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
