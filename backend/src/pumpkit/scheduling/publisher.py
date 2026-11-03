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
from pumpkit.scheduling.publishing import claim_next_due, publish_claimed, recover_stuck
from pumpkit.x_connection.x_publisher import XPublisher, get_x_publisher

# compose.yml's publisher healthcheck reads this exact path's age.
HEARTBEAT_FILE = Path("/tmp/pumpkit-publisher-heartbeat")
# A video's upload can take an hour, so publishes run side by side, each claimed by its own
# session as ADR 0007's SKIP LOCKED allows; this bounds the X calls and database connections.
PUBLISHES_AT_ONCE = 4


class Publishes:
    """
    The publishes under way, at most `at_once`; a publish outlives the pass that claimed it.
    Each failure is logged; with `raises`, `all_finished` raises the first since it last ran.
    """

    def __init__(self, at_once: int = PUBLISHES_AT_ONCE, *, raises: bool = False) -> None:
        self._at_once = at_once
        self._raises = raises
        self._under_way: set[asyncio.Task[None]] = set()
        self._finished = asyncio.Event()
        self._failure: Optional[BaseException] = None

    def has_room(self) -> bool:
        return len(self._under_way) < self._at_once

    def start(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        publisher: XPublisher,
        storage: FileStorage,
        clock: Clock,
        *,
        scheduled_post_id: str,
        claimed_at: datetime,
        stop: Optional[asyncio.Event] = None,
    ) -> None:
        async def publishing() -> None:
            async with session_maker() as db:
                await publish_claimed(
                    db,
                    publisher,
                    storage,
                    scheduled_post_id=scheduled_post_id,
                    claimed_at=claimed_at,
                    clock=clock,
                    stop=stop,
                )

        task = asyncio.create_task(publishing(), name=scheduled_post_id)
        self._under_way.add(task)
        task.add_done_callback(self._done)

    def _done(self, task: asyncio.Task[None]) -> None:
        self._under_way.discard(task)
        self._finished.set()
        failure = None if task.cancelled() else task.exception()
        if failure is not None:
            # Left in publishing, recovery settles it once its claim goes unrenewed.
            logger.error("Publishing Scheduled post %s failed", task.get_name(), exc_info=failure)
            if self._raises:
                self._failure = self._failure or failure

    async def one_finished(self) -> None:
        self._finished.clear()
        if self._under_way:
            await self._finished.wait()

    async def all_finished(self) -> None:
        while self._under_way:
            await asyncio.wait(self._under_way)
        failure, self._failure = self._failure, None
        if failure is not None:
            raise failure


async def run_pass(
    session_maker: async_sessionmaker[AsyncSession],
    publisher: XPublisher,
    storage: FileStorage,
    clock: Clock,
    stop: Optional[asyncio.Event] = None,
    *,
    files_swept_at: Optional[datetime] = None,
    publishes: Optional[Publishes] = None,
) -> Optional[datetime]:
    """
    Publish due Scheduled posts, then sweep. Given `publishes`, claim while they have room and
    leave them under way; without, publish one at a time. Returns when files were last swept.
    """
    waits = publishes is None
    under_way = publishes if publishes is not None else Publishes(at_once=1, raises=True)
    async with session_maker() as db:
        await recover_stuck(db, now=clock())
    while stop is None or not stop.is_set():
        if not under_way.has_room():
            if not waits:
                break
            await under_way.one_finished()
            continue
        # A session per claim and per publish: `publishing` commits as it goes.
        async with session_maker() as db:
            claimed_at = clock()
            scheduled_post_id = await claim_next_due(db, now=claimed_at)
        if scheduled_post_id is None:
            break
        under_way.start(
            session_maker,
            publisher,
            storage,
            clock,
            scheduled_post_id=scheduled_post_id,
            claimed_at=claimed_at,
            stop=stop,
        )
    if waits:
        await under_way.all_finished()
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
    publishes = Publishes()
    try:
        while not stop.is_set():
            try:
                if enabled:
                    files_swept_at = await run_pass(
                        session_maker,
                        publisher,
                        storage,
                        clock,
                        stop,
                        files_swept_at=files_swept_at,
                        publishes=publishes,
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
    finally:
        await publishes.all_finished()


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    # Stop calling X, wait for the posts X is being sent, then exit: compose allows 3 minutes.
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
