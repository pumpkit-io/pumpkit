"""Discarding a Draft on Postgres, whose foreign keys the SQLite suite doesn't enforce."""

import pytest

from tests.scheduling.test_discarding_a_draft import draft as draft
from tests.scheduling.test_discarding_a_draft import (
    test_a_discarded_draft_is_gone_and_its_idea_stays_not_written as test_a_discarded_draft_is_gone_and_its_idea_stays_not_written,
)
from tests.scheduling.test_discarding_a_draft import (
    test_its_media_and_their_files_are_deleted as test_its_media_and_their_files_are_deleted,
)
from tests.scheduling.test_discarding_a_draft import (
    test_its_upload_links_stop_working as test_its_upload_links_stop_working,
)
from tests.scheduling.test_discarding_a_draft import (
    test_the_generation_a_discarded_draft_used_stays_used as test_the_generation_a_discarded_draft_used_stays_used,
)

pytestmark = pytest.mark.postgres
