"""The Ideas a Brief's page offers under "Not written", which New post's recent Briefs count."""

import json
from pathlib import Path

import pytest

from pumpkit.posts.brief_reading import offered_ideas
from pumpkit.posts.models import Idea, Post
from pumpkit.posts.plans import Plan

# Shared with frontend/src/services/briefService.test.ts, which runs them on `notWrittenIdeas`.
CASES = json.loads((Path(__file__).parent / "offered_ideas_cases.json").read_text())
PLAN = Plan(
    core_idea="Ship small.",
    takeaway="Ship this week.",
    reasoning="",
    funnel="middle",
    desired_action="bookmark",
    format="post",
    length="short",
    structure="few_lines",
)


@pytest.mark.parametrize("case", CASES, ids=[case["note"] for case in CASES])
def test_the_ideas_offered(case):
    ideas = [
        (
            Idea(
                id=idea_id,
                whole_brief=idea_id == "whole",
                plan=None if idea_id in case.get("unplanned", []) else PLAN,
            ),
            None if state is None else Post(id=f"post_of_{idea_id}"),
        )
        for idea_id, state in case["ideas"]
    ]

    assert [idea.id for idea in offered_ideas(ideas)] == case["offered"]
