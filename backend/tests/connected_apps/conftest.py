import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from pumpkit.core.db.base import Base
from tests.oauth_app import CHALLENGE, REDIRECT, register


@pytest_asyncio.fixture
async def oauth_client(new_browser) -> str:
    """The id of a public app registered through Dynamic Client Registration."""
    return await register(new_browser(), REDIRECT, client_name="Gemini CLI")


@pytest.fixture
def authorize_params(oauth_client) -> dict[str, str]:
    """A valid authorize request from `oauth_client`; tests override or drop fields."""
    return {
        "client_id": oauth_client,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": "xyz",
    }


@pytest_asyncio.fixture
async def foreign_keys_session(tmp_path):
    """A session on its own database with SQLite's foreign keys on, as Postgres enforces them."""
    # The shared test engine leaves them off.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fk.db'}", poolclass=NullPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _foreign_keys_on(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()
