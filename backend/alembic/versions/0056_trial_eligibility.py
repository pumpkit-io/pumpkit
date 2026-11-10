"""Keep X account trial eligibility independently of deleted Users."""

import sqlalchemy as sa

from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trial_eligibility",
        sa.Column("key_id", sa.String(64), primary_key=True),
        sa.Column("fingerprint", sa.String(64), primary_key=True),
        sa.Column("eligible", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT 1 FROM trial_eligibility LIMIT 1")):
        raise RuntimeError("Retained trial eligibility requires a compatible backup to downgrade.")
    op.drop_table("trial_eligibility")
