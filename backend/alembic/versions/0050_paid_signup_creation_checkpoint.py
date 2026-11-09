"""Keep uncertain remote creation and cancellation intent durable."""

import sqlalchemy as sa

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "paid_signups",
        sa.Column("creation_state", sa.String(), nullable=False, server_default="not_started"),
    )
    op.add_column("paid_signups", sa.Column("creation_attempted_at", sa.DateTime(timezone=True)))
    op.add_column(
        "paid_signups",
        sa.Column("creation_dispatch_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("paid_signups", sa.Column("payment_method_id", sa.String()))
    op.add_column("paid_signups", sa.Column("cancel_requested_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE paid_signups SET creation_state = 'uncertain' WHERE status = 'pending'")
    op.execute("UPDATE paid_signups SET creation_state = 'confirmed' WHERE status = 'completed'")


def downgrade() -> None:
    op.drop_column("paid_signups", "cancel_requested_at")
    op.drop_column("paid_signups", "payment_method_id")
    op.drop_column("paid_signups", "creation_dispatch_count")
    op.drop_column("paid_signups", "creation_attempted_at")
    op.drop_column("paid_signups", "creation_state")
