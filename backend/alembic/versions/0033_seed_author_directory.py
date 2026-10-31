"""seed the Author directory with the accounts every Instance starts from

The seeds come from `alembic/data/author_seeds.json`, written once from the Operator's list by
`scripts/write_author_seeds.py`, so migrating needs no twitterapi.io key. A handle already in the
directory keeps its entry.

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-31 18:10:00.000000

"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEEDS = Path(__file__).parents[1] / "data" / "author_seeds.json"

_directory = sa.table(
    "author_directory",
    sa.column("handle", sa.String),
    sa.column("name", sa.String),
    sa.column("photo_url", sa.String),
    sa.column("added_at", sa.DateTime(timezone=True)),
    sa.column("source", sa.String),
)


def _seeds() -> list[dict]:
    return json.loads(SEEDS.read_text(encoding="utf-8"))


def upgrade() -> None:
    connection = op.get_bind()
    present = set(connection.execute(sa.select(_directory.c.handle)).scalars())
    now = datetime.now(timezone.utc)
    rows = [
        {
            "handle": seed["handle"],
            "name": seed["name"],
            "photo_url": seed["photo_url"],
            "added_at": now,
            "source": "seed",
        }
        for seed in _seeds()
        if seed["handle"] not in present
    ]
    if rows:
        op.bulk_insert(_directory, rows)


def downgrade() -> None:
    handles = [seed["handle"] for seed in _seeds()]
    op.execute(
        _directory.delete().where(_directory.c.source == "seed", _directory.c.handle.in_(handles))
    )
