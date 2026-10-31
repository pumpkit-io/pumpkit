"""the Author directory, the one home of each X account's name and photo

Every handle on any User's Persona, or fetched at all, gets an entry, carrying the photo its fetch
record stored, and the fetch record keeps only when it was fetched.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-31 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "author_directory",
        sa.Column("handle", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("photo_url", sa.String(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("handle"),
    )
    # Each of these handles was read from X when it was added, so it counts as a lookup.
    op.execute(
        """
        INSERT INTO author_directory (handle, name, photo_url, added_at, source)
        SELECT known.handle, NULL, author_fetches.photo_url, CURRENT_TIMESTAMP, 'lookup'
        FROM (
            SELECT handle FROM author_fetches
            UNION
            SELECT handle FROM inspiration_authors
        ) AS known
        LEFT JOIN author_fetches ON author_fetches.handle = known.handle
        """
    )
    with op.batch_alter_table("author_fetches", schema=None) as batch_op:
        batch_op.drop_column("photo_url")


def downgrade() -> None:
    with op.batch_alter_table("author_fetches", schema=None) as batch_op:
        batch_op.add_column(sa.Column("photo_url", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE author_fetches SET photo_url = (
            SELECT photo_url FROM author_directory
            WHERE author_directory.handle = author_fetches.handle
        )
        """
    )
    op.drop_table("author_directory")
