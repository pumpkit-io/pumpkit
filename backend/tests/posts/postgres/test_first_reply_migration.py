"""Migration 0063 on Postgres, by the test that covers it on SQLite."""

import pytest

from tests.posts.test_first_reply_migration import (
    test_downgrade_drops_the_flags_and_upgrade_reads_an_earlier_post_as_having_none as test_downgrade_drops_the_flags_and_upgrade_reads_an_earlier_post_as_having_none,
)

pytestmark = pytest.mark.postgres
