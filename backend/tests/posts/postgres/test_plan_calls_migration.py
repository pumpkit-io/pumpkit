"""Migration 0065 on Postgres, by the test that covers it on SQLite."""

import pytest

from tests.posts.test_plan_calls_migration import (
    test_upgrade_adds_the_plan_calls_table_and_downgrade_drops_it as test_upgrade_adds_the_plan_calls_table_and_downgrade_drops_it,
)

pytestmark = pytest.mark.postgres
