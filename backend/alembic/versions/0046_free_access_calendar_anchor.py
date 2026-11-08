"""Keep appended calendar offsets independent of clipped and purged grants."""

import sqlalchemy as sa

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("free_access", sa.Column("calendar_anchor", sa.DateTime(timezone=True)))
    op.add_column(
        "free_access", sa.Column("month_offset", sa.Integer(), nullable=False, server_default="0")
    )
    op.execute("UPDATE free_access SET calendar_anchor = starts_at")


def downgrade() -> None:
    op.drop_column("free_access", "month_offset")
    op.drop_column("free_access", "calendar_anchor")
