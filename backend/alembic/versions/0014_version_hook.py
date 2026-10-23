"""add the Hook's reasoning and library id to Version attempts

The draft and revision calls choose and write a Version's Hook, from a curated library when one
fits. The attempt stores the call's reasoning about the opening and the library id of the Hook it
opened with.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-20 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("hook_reasoning", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("hook_name", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.drop_column("hook_name")
        batch_op.drop_column("hook_reasoning")
