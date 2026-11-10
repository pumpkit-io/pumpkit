import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from pumpkit.core.db.base import Base


@pytest_asyncio.fixture
async def db_engine():
    url = os.environ.get("PUMPKIT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set PUMPKIT_TEST_POSTGRES_URL to run isolated PostgreSQL contention tests")
    schema = "contention_test_" + uuid4().hex
    admin = create_async_engine(url, poolclass=NullPool)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema, "application_name": schema}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest_asyncio.fixture
async def writing_session_maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)
