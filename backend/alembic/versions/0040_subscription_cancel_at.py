"""subscription cancel_at

Stripe records a cancellation either as `cancel_at_period_end` or, on flexible billing mode, as a
`cancel_at` date. Pumpkit now keeps only the date: a row cancelled at its period end gets that
period end, and the next sync fills in rows Stripe cancelled by date.

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-02 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cancel_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE subscriptions SET cancel_at = current_period_end WHERE cancel_at_period_end")
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.drop_column("cancel_at_period_end")


def downgrade() -> None:
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "cancel_at_period_end",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
    op.execute("UPDATE subscriptions SET cancel_at_period_end = cancel_at IS NOT NULL")
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.drop_column("cancel_at")
