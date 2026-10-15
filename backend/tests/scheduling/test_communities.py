import json
from pathlib import Path

import pytest

from pumpkit.scheduling.communities import NOT_A_COMMUNITY, community_id_from
from pumpkit.scheduling.rules import RuleBroken

# Shared with frontend/src/features/scheduledPosts/communities.test.ts.
CASES = json.loads((Path(__file__).parent / "community_paste_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[case["note"] for case in CASES])
def test_pasted_text_reads_as_a_community_id_or_is_refused(case):
    if case["id"] is None:
        with pytest.raises(RuleBroken) as refused:
            community_id_from(case["pasted"])
        assert refused.value.message == NOT_A_COMMUNITY
    else:
        assert community_id_from(case["pasted"]) == case["id"]
