from collections.abc import AsyncGenerator, Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.logger import logger
from app.db.urls import build_database_url


class DatabaseSessionHandler:
    def __init__(self):
        url_parts = dict(
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            database=settings.POSTGRES_DB,
            env=settings.ENV,
        )

        self.url: str = build_database_url(driver="default", **url_parts)
        self.engine: Engine = create_engine(self.url)
        self.session_maker: sessionmaker[Session] = sessionmaker(
            bind=self.engine, expire_on_commit=False
        )

        self.async_url: str = build_database_url(driver="asyncpg", **url_parts)
        self.async_engine: AsyncEngine = create_async_engine(self.async_url)
        self.async_session_maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.async_engine, class_=AsyncSession, expire_on_commit=False
        )


_db_session_handler: DatabaseSessionHandler = DatabaseSessionHandler()


def get_sync_db() -> Generator[Session, None, None]:
    with _db_session_handler.session_maker() as db:
        try:
            yield db
        except Exception as e:
            logger.error(f"Error within sync DB session: {e}")
            db.rollback()
            raise
        finally:
            db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with _db_session_handler.async_session_maker() as db:
        try:
            yield db
        except Exception as e:
            logger.error(f"Error within async DB session: {e}")
            await db.rollback()
            raise
        finally:
            await db.close()
