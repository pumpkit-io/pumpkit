"""Migration 0066 on Postgres, by the test that covers it on SQLite."""

import pytest

from tests.posts.test_attempts_outlive_their_post_migration import (
    test_upgrade_names_each_attempts_user_and_downgrade_drops_a_discarded_posts as test_upgrade_names_each_attempts_user_and_downgrade_drops_a_discarded_posts,
)

pytestmark = pytest.mark.postgres
