from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.core.logging import logger


async def database_is_reachable(db: AsyncSession) -> bool:
    try:
        await db.execute(text("SELECT 1"))
    except Exception as e:
        logger.error(f"Health check could not reach the database: {e}")
        return False
    return True
