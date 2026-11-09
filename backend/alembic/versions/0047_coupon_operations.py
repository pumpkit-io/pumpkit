"""Keep paid coverage and durable provider-backed coupon operations."""

import sqlalchemy as sa

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("paid_start", "paid_end", "paid_anchor"):
        op.add_column("subscriptions", sa.Column(name, sa.DateTime(timezone=True)))
    op.add_column("subscriptions", sa.Column("paid_allowance", sa.JSON()))
    op.add_column("free_access", sa.Column("coverage_starts_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE free_access SET coverage_starts_at = calendar_anchor")
    op.create_table(
        "coupon_operations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("coupon_id", sa.String(), sa.ForeignKey("coupons.id"), nullable=False),
        sa.Column(
            "claim_id",
            sa.String(),
            sa.ForeignKey("coupon_claims.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("revision_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("subscription_id", sa.String(), nullable=False),
        sa.Column("original", sa.JSON(), nullable=False),
        sa.Column("offer", sa.JSON(), nullable=False),
        sa.Column("acceptance", sa.JSON(), nullable=False),
        sa.Column("target", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("detail", sa.String()),
        sa.UniqueConstraint("user_id", "operation_id"),
    )
    for name in ("user_id", "coupon_id", "status"):
        op.create_index(f"ix_coupon_operations_{name}", "coupon_operations", [name])


def downgrade() -> None:
    op.drop_table("coupon_operations")
    op.drop_column("free_access", "coverage_starts_at")
    for name in ("paid_allowance", "paid_anchor", "paid_end", "paid_start"):
        op.drop_column("subscriptions", name)
