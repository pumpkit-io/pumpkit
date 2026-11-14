"""Migration 0064 on Postgres, by the test that covers it on SQLite."""

import pytest

from tests.posts.test_unwritten_feedback_migration import (
    test_downgrade_drops_the_feedback_and_upgrade_reads_an_earlier_post_with_no_failure as test_downgrade_drops_the_feedback_and_upgrade_reads_an_earlier_post_with_no_failure,
)

pytestmark = pytest.mark.postgres
