"""Keep accepted future interval changes recoverable."""

import sqlalchemy as sa

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_changes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("revision_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("customer_id", sa.String(), nullable=False),
        sa.Column("subscription_id", sa.String(), nullable=False),
        sa.Column("original", sa.JSON(), nullable=False),
        sa.Column("offer", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("detail", sa.String()),
        sa.UniqueConstraint("user_id", "operation_id"),
    )
    op.create_index("ix_plan_changes_user_id", "plan_changes", ["user_id"])
    op.create_index("ix_plan_changes_status", "plan_changes", ["status"])


def downgrade() -> None:
    op.drop_table("plan_changes")
