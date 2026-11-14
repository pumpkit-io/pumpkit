"""a paid signup keeps no state from the removed setup-mode Checkout flow

Revision ID: 0067
Revises: 0066
Create Date: 2026-11-14 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0067"
down_revision: Union[str, None] = "0066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("paid_signups", schema=None) as batch_op:
        batch_op.drop_column("payment_method_id")
        batch_op.drop_column("creation_dispatch_count")
        batch_op.drop_column("creation_attempted_at")
        batch_op.drop_column("creation_state")


def downgrade() -> None:
    with op.batch_alter_table("paid_signups", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("creation_state", sa.String(), nullable=False, server_default="not_started")
        )
        batch_op.add_column(sa.Column("creation_attempted_at", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column("creation_dispatch_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("payment_method_id", sa.String()))
    op.execute(
        "UPDATE paid_signups SET creation_state = 'confirmed' WHERE subscription_id IS NOT NULL"
    )
