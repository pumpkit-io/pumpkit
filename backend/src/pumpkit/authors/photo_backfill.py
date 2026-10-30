"""
Stores the X photo of each Inspiration author listed before Pumpkit kept photos. Run it once
after migrating, with `python -m pumpkit.authors.photo_backfill`.
"""

import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# InspirationAuthor names `User` by string, so the process needs auth's models mapped too.
import pumpkit.auth.models  # noqa: F401
from pumpkit.authors import service
from pumpkit.authors.x_reader import XReader, XReaderError, get_x_reader
from pumpkit.core.db.session import _db_session_handler
from pumpkit.core.logging import logger


@dataclass(frozen=True)
class BackfillResult:
    filled: int
    skipped: int


async def backfill_author_photos(
    session_maker: async_sessionmaker[AsyncSession], reader: XReader
) -> BackfillResult:
    """
    Read each listed handle without a photo from X, one twitterapi.io request each, and store
    only its photo: the posts and the refresh cooldown stay as they were. A handle that fails
    or comes back without a photo is logged and skipped, so a later run tries it again.
    """
    async with session_maker() as db:
        handles = await service.listed_handles_without_photo(db)
    filled = skipped = 0
    for handle in handles:
        try:
            photo_url = (await reader.fetch_recent_posts(handle)).photo_url
        except XReaderError as error:
            logger.warning(f"Skipped @{handle}'s photo: {error}")
            skipped += 1
            continue
        if photo_url is None:
            logger.warning(f"Skipped @{handle}'s photo: X returned none")
            skipped += 1
            continue
        # A commit per handle keeps what was filled if a later one interrupts the run.
        async with session_maker() as db:
            await service.store_photo(db, handle=handle, photo_url=photo_url)
            await db.commit()
        filled += 1
    return BackfillResult(filled=filled, skipped=skipped)


async def main() -> None:
    try:
        result = await backfill_author_photos(
            _db_session_handler.async_session_maker, get_x_reader()
        )
        logger.info(f"Author photo backfill done: {result.filled} filled, {result.skipped} skipped")
    finally:
        await _db_session_handler.async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
