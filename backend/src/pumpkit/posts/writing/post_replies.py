"""
The structured replies of the calls that write a single post's or a Thread's Versions, ported
from pumpkit-new-architecture-v5. Field order is deliberate: reasoning and choices before the post.

`first_reply` defaults to None only for Python: the SDK's strict schema still requires it,
nullable, as v5's does.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

HookType = Literal[
    "bold_claim",
    "callout",
    "curiosity_gap",
    "clear_outcome",
    "contrarian",
    "story",
    "number_list",
    "proof",
]
Lever = Literal[
    "payoff",
    "curiosity_gap",
    "surprise",
    "identity",
    "proof",
    "exclusivity",
    "loss_aversion",
    "vulnerability",
]
CtaType = Literal["none", "reply", "share", "follow", "bookmark", "click", "DM", "sign-up", "buy"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SketchedPost(_Strict):
    hook_levers: list[Lever]
    hook_types: list[HookType]
    hook_reasoning: str
    cta_type: CtaType
    post: str
    first_reply: Optional[str] = None


class SketchReview(_Strict):
    sketch_number: int
    keep: str
    drop: str


class MergedSketch(_Strict):
    reviews: list[SketchReview]
    reasoning: str
    hook_levers: list[Lever]
    hook_types: list[HookType]
    cta_type: CtaType
    post: str
    first_reply: Optional[str] = None


class HumanizedPost(_Strict):
    post: str
    first_reply: Optional[str] = None


class RevisedPost(_Strict):
    reasoning: str
    cta_type: CtaType
    post: str
    first_reply: Optional[str] = None


# No minItems or maxItems on `parts`: not every provider enforces them, so the count is checked
# after the call.
class SketchedThread(_Strict):
    hook_levers: list[Lever]
    hook_types: list[HookType]
    hook_reasoning: str
    cta_type: CtaType
    parts: list[str]


class MergedThread(_Strict):
    reviews: list[SketchReview]
    reasoning: str
    hook_levers: list[Lever]
    hook_types: list[HookType]
    cta_type: CtaType
    parts: list[str]


class HumanizedThread(_Strict):
    parts: list[str]


# The model reads the schema names, v5's and their thread equivalents. `refined_post`,
# `revised_post` and `refined_thread` also name the old path's replies, other classes: each call
# sends its own class's schema under that name.
SketchedPost.__name__ = "sketched_post"
MergedSketch.__name__ = "merged_sketch"
HumanizedPost.__name__ = "refined_post"
RevisedPost.__name__ = "revised_post"
SketchedThread.__name__ = "sketched_thread"
MergedThread.__name__ = "merged_thread"
HumanizedThread.__name__ = "refined_thread"
