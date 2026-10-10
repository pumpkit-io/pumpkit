"""`python -m app.publishing`: the publisher process (ADR 0007)."""

import asyncio
import signal
from datetime import timedelta

from app.core.clock import system_clock
from app.core.config import settings
from app.core.logger import logger
from app.core.posthog import posthog_client
from app.core.x_publisher import get_x_publisher
from app.db.session import _db_session_handler
from app.publishing.publisher import run


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
