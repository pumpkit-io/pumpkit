"""Preserve uncertainty for coupon deferrals dispatched before a process stops."""

import sqlalchemy as sa

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("coupon_operations", sa.Column("attempted_at", sa.DateTime(timezone=True)))
    op.add_column(
        "coupon_operations",
        sa.Column("dispatch_count", sa.Integer(), nullable=False, server_default="0"),
    )
    # Legacy attempts were committed after the RPC, so even zero cannot prove no dispatch.
    op.execute(
        "UPDATE coupon_operations SET attempted_at = created_at, dispatch_count = 1 WHERE status IN ('pending', 'refused')"
    )
    # A rejected replay may have released a claim while an older request was still running.
    op.execute(
        "UPDATE coupon_operations SET status = 'pending', resolved_at = NULL WHERE status = 'refused'"
    )


def downgrade() -> None:
    op.drop_column("coupon_operations", "dispatch_count")
    op.drop_column("coupon_operations", "attempted_at")
