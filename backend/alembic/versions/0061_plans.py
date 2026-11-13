"""a Brief keeps how it was planned, and each Idea its Plan

Revision ID: 0061
Revises: 0060
Create Date: 2026-11-14 01:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0061"
down_revision: Union[str, None] = "0060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
# The Versions' Format type, which already exists.
_FORMAT = sa.Enum("post", "thread", name="version_format_enum").with_variant(
    postgresql.ENUM("post", "thread", name="version_format_enum", create_type=False),
    "postgresql",
)
_FUNNEL = sa.Enum("top", "middle", "bottom", name="funnel_enum")
_DESIRED_ACTION = sa.Enum(
    "dwell_time",
    "reply",
    "bookmark",
    "repost",
    "share",
    "follow",
    "trust",
    "click",
    "DM",
    "sign-up",
    "buy",
    name="desired_action_enum",
)
_LENGTH = sa.Enum("short", "medium", "long", name="length_enum")
_STRUCTURE = sa.Enum(
    "one_line",
    "few_lines",
    "hook_list_closer",
    "hook_problem_insight_closer",
    "hook_story_insight_closer",
    "hook_playbook_closer",
    name="structure_enum",
)
_NEW_TYPES = (_FUNNEL, _DESIRED_ACTION, _LENGTH, _STRUCTURE)


def upgrade() -> None:
    for new_type in _NEW_TYPES:
        new_type.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("briefs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("positioning", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("planning_reasoning", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("planning_model", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("planning_usage", _JSON, nullable=True))
    with op.batch_alter_table("ideas", schema=None) as batch_op:
        # Every Idea stored so far is its Brief's only one, so it covers the whole Brief.
        batch_op.add_column(
            sa.Column("whole_brief", sa.Boolean(), server_default=sa.true(), nullable=False)
        )
        batch_op.add_column(sa.Column("core_idea", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("takeaway", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("plan_reasoning", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("funnel", _FUNNEL, nullable=True))
        batch_op.add_column(sa.Column("desired_action", _DESIRED_ACTION, nullable=True))
        batch_op.add_column(sa.Column("format", _FORMAT, nullable=True))
        batch_op.add_column(sa.Column("length", _LENGTH, nullable=True))
        batch_op.add_column(sa.Column("structure", _STRUCTURE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ideas", schema=None) as batch_op:
        batch_op.drop_column("structure")
        batch_op.drop_column("length")
        batch_op.drop_column("format")
        batch_op.drop_column("desired_action")
        batch_op.drop_column("funnel")
        batch_op.drop_column("plan_reasoning")
        batch_op.drop_column("takeaway")
        batch_op.drop_column("core_idea")
        batch_op.drop_column("whole_brief")
    with op.batch_alter_table("briefs", schema=None) as batch_op:
        batch_op.drop_column("planning_usage")
        batch_op.drop_column("planning_model")
        batch_op.drop_column("planning_reasoning")
        batch_op.drop_column("positioning")
    for new_type in _NEW_TYPES:
        new_type.drop(op.get_bind(), checkfirst=True)
