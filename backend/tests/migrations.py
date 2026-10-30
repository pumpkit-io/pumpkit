"""Running Alembic against the test database, for the tests of a migration's outcome."""

from pathlib import Path
from typing import Callable

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy import Connection


def _alembic(connection: Connection, run: Callable[[Config], None]) -> None:
    # No ini file, so Alembic leaves the test run's logging alone.
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    config.attributes["connection"] = connection
    run(config)


async def migrate(db_engine, run: Callable[[Config], None]) -> None:
    """Runs one Alembic command, such as `lambda config: command.upgrade(config, "0021")`."""
    async with db_engine.begin() as connection:
        await connection.run_sync(_alembic, run)


def insert(connection: Connection, table: str, **values) -> None:
    """A raw row, for the schema as it was before a migration, which the models no longer match."""
    columns = [sa.column(name) for name in values]
    connection.execute(sa.table(table, *columns).insert().values(**values))
