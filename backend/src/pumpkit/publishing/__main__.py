"""`python -m pumpkit.publishing`: the publisher process (ADR 0007)."""

import asyncio
import signal
from datetime import timedelta

from pumpkit.core.analytics import posthog_client
from pumpkit.core.config import settings
from pumpkit.core.db.session import _db_session_handler
from pumpkit.core.logging import logger
from pumpkit.core.time import system_clock
from pumpkit.publishing.publisher import run
from pumpkit.x_connection.x_publisher import get_x_publisher


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
