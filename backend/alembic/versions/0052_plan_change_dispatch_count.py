"""Keep uncertain price-update replays guarded across dispatch ownership changes."""

import sqlalchemy as sa

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plan_changes",
        sa.Column("dispatch_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("plan_changes", "dispatch_count")
