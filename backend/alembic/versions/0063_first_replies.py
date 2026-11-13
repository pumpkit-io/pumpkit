"""the Text, each Version and each Scheduled post record a first reply

Revision ID: 0063
Revises: 0062
Create Date: 2026-11-14 07:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0063"
down_revision: Union[str, None] = "0062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = {
    "posts": ["text_first_reply"],
    "version_attempts": ["first_reply", "starting_text_first_reply"],
    "scheduled_posts": ["first_reply"],
}


def upgrade() -> None:
    for table, columns in _COLUMNS.items():
        with op.batch_alter_table(table, schema=None) as batch_op:
            for column in columns:
                batch_op.add_column(
                    sa.Column(column, sa.Boolean(), server_default=sa.false(), nullable=False)
                )


def downgrade() -> None:
    for table, columns in _COLUMNS.items():
        with op.batch_alter_table(table, schema=None) as batch_op:
            for column in reversed(columns):
                batch_op.drop_column(column)
