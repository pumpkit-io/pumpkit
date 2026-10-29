"""name a Version attempt's Sketch columns after the Sketch

The text Pumpkit writes before rewriting it is the Sketch, so "draft" is free for a Post's
status. Its Parts, model and usage are renamed; no data changes.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-28 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RENAMES = [
    ("draft_parts", "sketch_parts"),
    ("writing_model", "sketch_model"),
    ("writing_usage", "sketch_usage"),
]


def upgrade() -> None:
    for old, new in _RENAMES:
        op.alter_column("version_attempts", old, new_column_name=new)


def downgrade() -> None:
    for old, new in _RENAMES:
        op.alter_column("version_attempts", new, new_column_name=old)
