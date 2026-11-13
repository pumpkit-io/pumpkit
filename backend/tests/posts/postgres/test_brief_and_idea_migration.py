"""Migration 0060 on Postgres, by the tests that cover it on SQLite."""

import pytest

from tests.posts.test_brief_and_idea_migration import bob as bob
from tests.posts.test_brief_and_idea_migration import (
    posts_storing_their_briefs as posts_storing_their_briefs,
)
from tests.posts.test_brief_and_idea_migration import (
    test_a_post_started_after_the_upgrade_is_read_back_with_its_brief as test_a_post_started_after_the_upgrade_is_read_back_with_its_brief,
)
from tests.posts.test_brief_and_idea_migration import (
    test_downgrade_gives_a_post_whose_corpus_was_set_to_none_an_empty_one as test_downgrade_gives_a_post_whose_corpus_was_set_to_none_an_empty_one,
)
from tests.posts.test_brief_and_idea_migration import (
    test_downgrade_keeps_each_posts_brief_and_gives_a_post_without_a_corpus_an_empty_one as test_downgrade_keeps_each_posts_brief_and_gives_a_post_without_a_corpus_an_empty_one,
)
from tests.posts.test_brief_and_idea_migration import (
    test_upgrade_gives_each_post_an_idea_of_a_brief_of_its_own as test_upgrade_gives_each_post_an_idea_of_a_brief_of_its_own,
)

pytestmark = pytest.mark.postgres
