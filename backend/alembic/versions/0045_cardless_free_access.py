"""Separate protected claims from account-bound benefits and acceptance evidence."""

import sqlalchemy as sa

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coupon_claims",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("coupon_id", sa.String(), sa.ForeignKey("coupons.id"), nullable=False),
        sa.Column("key_id", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.UniqueConstraint("coupon_id", "key_id", "fingerprint"),
    )
    op.create_index(
        op.f("ix_coupon_claims_coupon_claims_coupon_id"), "coupon_claims", ["coupon_id"]
    )
    op.create_table(
        "coupon_history",
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
    )
    op.create_table(
        "free_access",
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
        sa.Column("months", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("allowance", sa.JSON(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acceptance", sa.JSON(), nullable=False),
        sa.UniqueConstraint("user_id", "operation_id"),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_free_access_positive_period")),
        sa.CheckConstraint("months > 0", name=op.f("ck_free_access_positive_months")),
    )
    for column in ("user_id", "coupon_id", "ends_at"):
        op.create_index(op.f(f"ix_free_access_free_access_{column}"), "free_access", [column])
    op.create_table("account_file_deletions", sa.Column("key", sa.String(), primary_key=True))


def downgrade() -> None:
    op.drop_table("account_file_deletions")
    op.drop_table("free_access")
    op.drop_table("coupon_history")
    op.drop_table("coupon_claims")
