"""The publisher (ADR 0007): a process of its own. Run it with `python -m pumpkit.scheduling.publisher`."""

import asyncio
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Models name `User` by string, so the process needs every model mapped, not just the ones it imports.
import pumpkit.models  # noqa: F401
import pumpkit.posts.media_upload_links as media_upload_links
from pumpkit.core.analytics import posthog_client
from pumpkit.core.config import settings
from pumpkit.core.db.session import _db_session_handler
from pumpkit.core.logging import logger
from pumpkit.core.storage import FileStorage, get_file_storage
from pumpkit.core.time import Clock, system_clock
from pumpkit.scheduling.media_sweep import (
    FILES_SWEPT_EVERY,
    delete_unnamed_files,
    delete_unreferenced_media,
)
from pumpkit.scheduling.publishing import publish_next_due, recover_stuck
from pumpkit.x_connection.x_publisher import XPublisher, get_x_publisher

# compose.yml's publisher healthcheck reads this exact path's age.
HEARTBEAT_FILE = Path("/tmp/pumpkit-publisher-heartbeat")


async def run_pass(
    session_maker: async_sessionmaker[AsyncSession],
    publisher: XPublisher,
    storage: FileStorage,
    clock: Clock,
    stop: Optional[asyncio.Event] = None,
    *,
    files_swept_at: Optional[datetime] = None,
) -> Optional[datetime]:
    """
    Publish every due Scheduled post (only the one in hand once `stop` is set), then sweep Media
    and expired upload links.
    Returns when it last swept files, for the next pass; a failed sweep is logged, not raised.
    """
    async with session_maker() as db:
        await recover_stuck(db, now=clock())
    while stop is None or not stop.is_set():
        # A session per Scheduled post: `publishing` commits as it goes.
        async with session_maker() as db:
            if not await publish_next_due(db, publisher, storage, clock=clock):
                break
    if stop is not None and stop.is_set():
        return files_swept_at
    try:
        async with session_maker() as db:
            await delete_unreferenced_media(db, storage, now=clock())
    except Exception:
        logger.exception("Deleting unreferenced Media failed; trying again next pass")
    try:
        async with session_maker() as db:
            await media_upload_links.delete_expired(db, now=clock())
            await db.commit()
    except Exception:
        logger.exception("Deleting expired upload links failed; trying again next pass")
    now = clock()
    if files_swept_at is not None and now - files_swept_at < FILES_SWEPT_EVERY:
        return files_swept_at
    try:
        async with session_maker() as db:
            await delete_unnamed_files(db, storage, now=now)
    except Exception:
        logger.exception("Deleting stored files no Media names failed; trying again later")
    return now


async def run(
    session_maker: async_sessionmaker[AsyncSession],
    publisher: XPublisher,
    storage: FileStorage,
    clock: Clock,
    *,
    poll_interval: timedelta,
    stop: asyncio.Event,
    heartbeat: Optional[Path] = None,
    enabled: bool = True,
) -> None:
    """
    Run a pass every `poll_interval` until `stop` is set. A failed pass is logged and retried.
    Each pass that completes touches `heartbeat`, which the container healthcheck reads.
    With `enabled` false it skips the passes but keeps the heartbeat, so the container stays healthy.
    """
    files_swept_at: Optional[datetime] = None
    while not stop.is_set():
        try:
            if enabled:
                files_swept_at = await run_pass(
                    session_maker, publisher, storage, clock, stop, files_swept_at=files_swept_at
                )
        except Exception:
            logger.exception("Publisher pass failed; trying again next interval")
        else:
            if heartbeat is not None:
                heartbeat.touch()
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
    if settings.PUBLISHER_ENABLED:
        logger.info(f"Publisher started, polling every {interval.total_seconds():g}s")
    else:
        logger.warning("PUBLISHER_ENABLED is false: the publisher publishes nothing")
    try:
        await run(
            _db_session_handler.async_session_maker,
            get_x_publisher(),
            get_file_storage(),
            system_clock,
            poll_interval=interval,
            stop=stop,
            heartbeat=HEARTBEAT_FILE,
            enabled=settings.PUBLISHER_ENABLED,
        )
    finally:
        logger.info("Publisher stopping")
        posthog_client.shutdown()
        await _db_session_handler.async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
