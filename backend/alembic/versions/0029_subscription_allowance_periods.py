"""store what a Subscription's Allowance periods hang on: its Trial and billing cycle anchor

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-31 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("trial_start", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("billing_cycle_anchor", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.drop_column("billing_cycle_anchor")
        batch_op.drop_column("trial_end")
        batch_op.drop_column("trial_start")
