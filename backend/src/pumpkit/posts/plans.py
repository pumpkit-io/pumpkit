"""An Idea's Plan: what Pumpkit decides about a Post before writing it (ADR 0025)."""

from dataclasses import dataclass
from typing import Literal, Optional

from pumpkit.posts.formats import Format

# Who the Post is for: people who don't know the User yet, who are deciding, or who are ready to act.
Funnel = Literal["top", "middle", "bottom"]
DesiredAction = Literal[
    "dwell_time",
    "reply",
    "bookmark",
    "repost",
    "share",
    "follow",
    "trust",
    "click",
    "DM",
    "sign-up",
    "buy",
]

# Which desired actions sit naturally at each funnel stage, as the plan prompt and the guide list them.
FUNNEL_ACTIONS: dict[Funnel, frozenset[DesiredAction]] = {
    "top": frozenset({"dwell_time", "reply", "repost", "share", "follow"}),
    "middle": frozenset({"dwell_time", "reply", "bookmark", "follow", "trust", "click"}),
    "bottom": frozenset({"click", "DM", "sign-up", "buy"}),
}

Length = Literal["short", "medium", "long"]
LENGTH_SHORT: Length = "short"
ShortStructure = Literal["one_line", "few_lines"]
# Every structure but the short ones, which a Thread can't take.
ThreadStructure = Literal[
    "hook_list_closer",
    "hook_problem_insight_closer",
    "hook_story_insight_closer",
    "hook_playbook_closer",
]
Structure = Literal[ShortStructure, ThreadStructure]


@dataclass(frozen=True)
class Plan:
    core_idea: str
    takeaway: str
    # Why the planner made the choices below. Only kept, never shown.
    reasoning: str
    funnel: Funnel
    desired_action: DesiredAction
    format: Format
    # None for a Thread.
    length: Optional[Length]
    structure: Structure
