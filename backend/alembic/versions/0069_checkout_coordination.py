"""Durable Checkout dispatch and Instance fence."""

import secrets

import sqlalchemy as sa

from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("paid_signups") as batch:
        batch.add_column(
            sa.Column("checkout_contract", sa.Integer(), nullable=False, server_default="0")
        )
    table = op.create_table(
        "billing_checkout_fence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instance_id", sa.String(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("closed", sa.Boolean(), nullable=False),
        sa.Column("config_fingerprint", sa.String(), nullable=True),
        sa.Column("stable_config_fingerprint", sa.String(), nullable=True),
        sa.Column("receipt", sa.String(), nullable=True),
        sa.Column("evidence_digest", sa.String(), nullable=True),
        sa.Column("source_managed", sa.Boolean(), nullable=True),
        sa.Column("released_receipt", sa.String(), nullable=True),
        sa.Column("released_generation", sa.Integer(), nullable=True),
        sa.Column("released_fingerprint", sa.String(), nullable=True),
        sa.Column("released_evidence_digest", sa.String(), nullable=True),
    )
    op.bulk_insert(
        table, [{"id": 1, "instance_id": secrets.token_hex(24), "generation": 0, "closed": False}]
    )
    op.create_table(
        "billing_checkout_dispatches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("settled", sa.Boolean(), nullable=False),
        sa.Column("provider_finished", sa.Boolean(), nullable=False),
        sa.Column("provider_resolution_required", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_billing_checkout_dispatches_user_id", "billing_checkout_dispatches", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("billing_checkout_dispatches")
    op.drop_table("billing_checkout_fence")
    with op.batch_alter_table("paid_signups") as batch:
        batch.drop_column("checkout_contract")
