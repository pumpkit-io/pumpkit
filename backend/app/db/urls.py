"""Postgres connection URLs shared by the app and Alembic.

No app imports, so Alembic can use this without loading settings.
"""

import urllib.parse
from typing import Literal

Driver = Literal["psycopg2", "asyncpg", "default"]

# The sync driver is pinned explicitly: SQLAlchemy 2.1 defaults a bare
# `postgresql://` URL to psycopg v3, which is not installed (psycopg2 is).
_SCHEMES: dict[str, str] = {
    "psycopg2": "postgresql+psycopg2",
    "asyncpg": "postgresql+asyncpg",
    "default": "postgresql+psycopg2",
}
_SSL_QUERY: dict[str, str] = {
    "psycopg2": "?sslmode=require",
    "asyncpg": "?ssl=require",
    "default": "?sslmode=require",
}


def build_database_url(
    *,
    driver: Driver,
    user: str,
    password: str,
    host: str,
    port: str,
    database: str,
    env: str,
) -> str:
    """Require SSL when env == 'prod': managed Postgres in production requires TLS."""
    quoted_password = urllib.parse.quote_plus(password)
    ssl_query = _SSL_QUERY[driver] if env == "prod" else ""
    return f"{_SCHEMES[driver]}://{user}:{quoted_password}@{host}:{port}/{database}{ssl_query}"
