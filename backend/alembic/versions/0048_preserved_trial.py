"""Distinguish preserved introductory Trials from paid coverage."""

import sqlalchemy as sa

from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("preserved_trial", sa.Boolean()))


def downgrade() -> None:
    op.drop_column("subscriptions", "preserved_trial")
