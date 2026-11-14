"""Migration 0066 on Postgres, by the tests that cover it on SQLite."""

import pytest

from tests.posts.test_attempts_outlive_their_post_migration import (
    test_downgrade_refuses_while_a_discarded_posts_attempts_are_kept as test_downgrade_refuses_while_a_discarded_posts_attempts_are_kept,
)
from tests.posts.test_attempts_outlive_their_post_migration import (
    test_upgrade_names_each_attempts_user_after_a_downgrade as test_upgrade_names_each_attempts_user_after_a_downgrade,
)

pytestmark = pytest.mark.postgres
