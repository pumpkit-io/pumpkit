"""Migration 0062 on Postgres, by the tests that cover it on SQLite."""

import pytest

from tests.posts.test_written_from_sketches_migration import (
    test_a_single_post_written_after_the_upgrade_keeps_its_sketches as test_a_single_post_written_after_the_upgrade_keeps_its_sketches,
)
from tests.posts.test_written_from_sketches_migration import (
    test_downgrade_drops_the_columns_and_upgrade_leaves_an_earlier_version_without_them as test_downgrade_drops_the_columns_and_upgrade_leaves_an_earlier_version_without_them,
)

pytestmark = pytest.mark.postgres
