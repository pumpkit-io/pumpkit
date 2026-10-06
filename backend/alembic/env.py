from __future__ import annotations

import os
import re
import sys
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the `app` package importable when Alembic runs.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

load_dotenv()

from app.db import models  # noqa: F401,E402
from app.db.base import Base  # noqa: E402
from app.db.urls import build_database_url  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_required_setting(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Environment variable '{key}' is not set")
    return value


def build_connection_url() -> str:
    return build_database_url(
        driver="psycopg2",
        user=get_required_setting("POSTGRES_USER"),
        password=get_required_setting("POSTGRES_PASSWORD"),
        host=get_required_setting("POSTGRES_HOST"),
        port=get_required_setting("POSTGRES_PORT"),
        database=get_required_setting("POSTGRES_DB"),
        env=os.getenv("ENV", "local"),
    )


def process_revision_directives(context, revision, directives) -> None:
    if not directives:
        return
    script = directives[0]

    # Revision IDs are sequential four-digit numbers instead of Alembic's random hashes.
    versions_dir = os.path.join(os.path.dirname(__file__), "versions")
    max_num = 0
    for filename in os.listdir(versions_dir):
        match = re.match(r"(\d{4})_", filename)
        if match:
            max_num = max(max_num, int(match.group(1)))
    script.rev_id = f"{max_num + 1:04d}"


def run_migrations_offline() -> None:
    url = build_connection_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    config.set_main_option("sqlalchemy.url", build_connection_url())
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
            process_revision_directives=process_revision_directives,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
