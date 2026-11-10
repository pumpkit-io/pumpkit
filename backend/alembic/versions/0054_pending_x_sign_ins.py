"""Prepare browser-bound X sign-in attempts without an existing User."""

import sqlalchemy as sa

from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_x_sign_ins",
        sa.Column("state_hash", sa.String(), primary_key=True),
        sa.Column("browser_secret_hash", sa.String(), nullable=False),
        sa.Column("code_verifier_encrypted", sa.Text(), nullable=False),
        sa.Column("return_to", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expires_at > created_at", name="expires_at_gt_created_at"),
    )
    op.create_index(
        "ix_pending_x_sign_ins_pending_x_sign_ins_expires_at", "pending_x_sign_ins", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pending_x_sign_ins_pending_x_sign_ins_expires_at", table_name="pending_x_sign_ins"
    )
    op.drop_table("pending_x_sign_ins")
