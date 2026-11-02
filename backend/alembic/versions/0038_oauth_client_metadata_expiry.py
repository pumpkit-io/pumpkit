"""when an app's cached metadata document goes stale

An app identified by a Client ID Metadata Document keeps the document it was last fetched with
in its `oauth_clients` row. `metadata_expires_at` says when to fetch it again: 24 hours after the
fetch, or sooner when the document's `Cache-Control: max-age` says so (at least 5 minutes).

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-01 23:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "oauth_clients",
        sa.Column("metadata_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("oauth_clients", "metadata_expires_at")
