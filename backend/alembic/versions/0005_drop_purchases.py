"""drop one-off purchases

Pumpkit bills only by Subscription (see docs/adr/0003-subscription-only-billing.md),
so the `purchases` table and its status enum go. No deployment holds real data,
so nothing is migrated. The downgrade recreates the table empty.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-04 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES: tuple[tuple[str, list[str]], ...] = (
    ("ix_purchases_purchases_product_id", ["product_id"]),
    ("ix_purchases_purchases_status", ["status"]),
    ("ix_purchases_purchases_stripe_charge_id", ["stripe_charge_id"]),
    ("ix_purchases_purchases_stripe_payment_intent_id", ["stripe_payment_intent_id"]),
    ("ix_purchases_purchases_user_id", ["user_id"]),
    ("ix_purchases_user_id_created_at", ["user_id", "created_at"]),
)


def upgrade() -> None:
    with op.batch_alter_table("purchases", schema=None) as batch_op:
        for name, _ in _INDEXES:
            batch_op.drop_index(batch_op.f(name))
    op.drop_table("purchases")
    sa.Enum(name="purchase_status_enum").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.create_table(
        "purchases",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("product_id", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "paid",
                "refunded",
                "partially_refunded",
                "disputed",
                "failed",
                name="purchase_status_enum",
            ),
            nullable=False,
        ),
        sa.Column("stripe_checkout_session_id", sa.String(), nullable=False),
        sa.Column("stripe_payment_intent_id", sa.String(), nullable=True),
        sa.Column("stripe_charge_id", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("amount_subtotal_cents", sa.BigInteger(), nullable=False),
        sa.Column("amount_tax_cents", sa.BigInteger(), nullable=True),
        sa.Column("amount_total_cents", sa.BigInteger(), nullable=True),
        sa.Column("refunded_amount_cents", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_purchases_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchases")),
        sa.UniqueConstraint(
            "stripe_checkout_session_id", name=op.f("uq_purchases_stripe_checkout_session_id")
        ),
    )
    with op.batch_alter_table("purchases", schema=None) as batch_op:
        for name, columns in _INDEXES:
            batch_op.create_index(batch_op.f(name), columns, unique=False)
