"""Coupon issuance records keep code digests and protected recipient assignments."""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coupons",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("code_digest", sa.String(64), nullable=False),
        sa.Column("benefit_kind", sa.String(), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False),
        sa.Column("max_redemptions", sa.Integer(), nullable=False),
        sa.Column("redeemed_count", sa.Integer(), nullable=False),
        sa.Column("plan_keys", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unclaimable_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipient_restricted", sa.Boolean(), nullable=False),
        sa.Column("recipient_key_id", sa.String(64), nullable=True),
        sa.Column("recipient_fingerprint", sa.String(64), nullable=True),
        sa.CheckConstraint("months > 0", name=op.f("ck_coupons_positive_months")),
        sa.CheckConstraint(
            "max_redemptions > 0", name=op.f("ck_coupons_positive_redemption_limit")
        ),
        sa.CheckConstraint(
            "redeemed_count >= 0 AND redeemed_count <= max_redemptions",
            name=op.f("ck_coupons_redemption_capacity"),
        ),
        sa.CheckConstraint(
            "benefit_kind = 'free_months'", name=op.f("ck_coupons_supported_benefit")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coupons")),
        sa.UniqueConstraint("code_digest", name=op.f("uq_coupons_code_digest")),
    )
    op.create_index(op.f("ix_coupons_coupons_unclaimable_at"), "coupons", ["unclaimable_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_coupons_coupons_unclaimable_at"), table_name="coupons")
    op.drop_table("coupons")
