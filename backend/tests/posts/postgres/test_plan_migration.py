"""Migration 0061 on Postgres, by the tests that cover it on SQLite."""

import pytest

from tests.posts.test_plan_migration import (
    test_a_post_started_after_the_upgrade_is_read_back_with_its_plan as test_a_post_started_after_the_upgrade_is_read_back_with_its_plan,
)
from tests.posts.test_plan_migration import (
    test_downgrade_drops_the_plan_and_upgrade_leaves_an_earlier_post_without_one as test_downgrade_drops_the_plan_and_upgrade_leaves_an_earlier_post_without_one,
)

pytestmark = pytest.mark.postgres
