"""Retain a separate X account fingerprint on coupon claims."""

import sqlalchemy as sa

from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("coupon_claims") as batch:
        batch.add_column(sa.Column("x_fingerprint", sa.String(64), nullable=True))
        batch.create_unique_constraint(
            "uq_coupon_claims_coupon_id_key_id_x_fingerprint",
            ["coupon_id", "key_id", "x_fingerprint"],
        )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT 1 FROM coupon_claims WHERE x_fingerprint IS NOT NULL LIMIT 1")
    ):
        raise RuntimeError("Retained X coupon claims require a compatible backup to downgrade.")
    with op.batch_alter_table("coupon_claims") as batch:
        batch.drop_constraint("uq_coupon_claims_coupon_id_key_id_x_fingerprint", type_="unique")
        batch.drop_column("x_fingerprint")
