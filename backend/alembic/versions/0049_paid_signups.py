"""Record explicit paid signup intent before provider writes."""

import sqlalchemy as sa

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("terms_acceptances", sa.Column("paid_offer", sa.JSON()))
    op.create_table(
        "paid_signups",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("revision_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("customer_id", sa.String()),
        sa.Column("session_id", sa.String()),
        sa.Column("subscription_id", sa.String()),
        sa.Column("offer", sa.JSON(), nullable=False),
        sa.Column("acceptance", sa.JSON(), nullable=False),
        sa.Column("first_payment_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("detail", sa.String()),
        sa.UniqueConstraint("user_id", "operation_id"),
    )
    op.create_index("ix_paid_signups_user_id", "paid_signups", ["user_id"])
    op.create_index("ix_paid_signups_status", "paid_signups", ["status"])


def downgrade() -> None:
    op.drop_table("paid_signups")
    op.drop_column("terms_acceptances", "paid_offer")
