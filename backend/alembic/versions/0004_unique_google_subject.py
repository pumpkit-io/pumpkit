"""make a Google account link to at most one User

Google sign-in finds the User by the Google identity's `subject` first, so a
`subject` must belong to one Google identity only. The unique constraint on
`(user_id, subject)` allowed the same Google account to be linked to two Users;
`subject` alone becomes unique, and its unique index replaces the plain one.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-04 21:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_google_identities_user_id_subject", "google_identities", type_="unique")
    op.drop_index("ix_google_identities_google_identities_subject", table_name="google_identities")
    op.create_unique_constraint("uq_google_identities_subject", "google_identities", ["subject"])


def downgrade() -> None:
    op.drop_constraint("uq_google_identities_subject", "google_identities", type_="unique")
    op.create_index(
        "ix_google_identities_google_identities_subject",
        "google_identities",
        ["subject"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_google_identities_user_id_subject", "google_identities", ["user_id", "subject"]
    )
