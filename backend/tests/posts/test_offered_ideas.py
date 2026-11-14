"""The Ideas a Brief's page offers under "Not written", which New post's recent Briefs count."""

import json
from pathlib import Path

import pytest

from pumpkit.posts.brief_reading import offered_ideas
from pumpkit.posts.models import Idea, Post

# Shared with frontend/src/services/briefService.test.ts, which runs them on `notWrittenIdeas`.
CASES = json.loads((Path(__file__).parent / "offered_ideas_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[case["note"] for case in CASES])
def test_the_ideas_offered(case):
    ideas = [
        (
            Idea(id=idea_id, whole_brief=idea_id == "whole"),
            None if state is None else Post(id=f"post_of_{idea_id}"),
        )
        for idea_id, state in case["ideas"]
    ]

    assert [idea.id for idea in offered_ideas(ideas)] == case["offered"]
