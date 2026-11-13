"""Planning a Brief: one model call that returns its Ideas, each with a Plan (ADR 0025)."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal, Optional, Sequence, Union

from pydantic import BaseModel, ConfigDict

from pumpkit.core.config import settings
from pumpkit.core.llm import LLM, LLMError
from pumpkit.core.text import drop_unstorable
from pumpkit.posts.formats import FORMAT_POST
from pumpkit.posts.plans import LENGTH_SHORT, DesiredAction, Funnel, Length, Plan, Structure
from pumpkit.posts.writing.constants import CACHE_TTL, MAX_SPLIT_IDEAS, MAX_TOKENS
from pumpkit.posts.writing.prompts.plan import SHORT_LIMIT, is_short_only, plan_prompt, plan_user

logger = logging.getLogger(__name__)

# The request waits on the plan, so the call gets this long before it counts as failed.
PLAN_CALL_SECONDS = 120.0

_PromptFunnel = Literal["TOF", "MOF", "BOF"]
_FUNNELS: dict[_PromptFunnel, Funnel] = {"TOF": "top", "MOF": "middle", "BOF": "bottom"}
_ShortStructure = Literal["one_line", "few_lines"]
_SHORT_STRUCTURES: tuple[Structure, ...] = ("one_line", "few_lines")

# Which desired actions sit naturally at each funnel stage, as the plan prompt lists them.
_FUNNEL_ACTIONS: dict[Funnel, set[DesiredAction]] = {
    "top": {"dwell_time", "reply", "repost", "share", "follow"},
    "middle": {"dwell_time", "reply", "bookmark", "follow", "trust", "click"},
    "bottom": {"click", "DM", "sign-up", "buy"},
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Field order matters: the idea first, then the reasoning, then the four choices it argues for.
class _PlannedIdea(_Strict):
    core_idea: str
    takeaway: str
    reasoning: str
    funnel: _PromptFunnel
    desired_action: DesiredAction


class _PlannedPost(_PlannedIdea):
    format: Length
    structure: Structure


class _PlannedShortPost(_PlannedIdea):
    format: Literal["short"]
    structure: _ShortStructure


class PostIdeas(_Strict):
    """The plan call's answer: always one post for the whole Brief, and one per idea on a split."""

    reasoning: str
    single_idea: _PlannedPost
    split_ideas: Optional[list[_PlannedPost]]


class ShortPostIdeas(_Strict):
    """The answer on an account that holds only a short post, which the schema then enforces."""

    reasoning: str
    single_idea: _PlannedShortPost
    split_ideas: Optional[list[_PlannedShortPost]]


_Planned = Union[_PlannedPost, _PlannedShortPost]

# The model reads the schema names.
PostIdeas.__name__ = "post_ideas"
ShortPostIdeas.__name__ = "post_ideas"


@dataclass(frozen=True)
class PlannedBrief:
    """What the plan call decided for a Brief, with the Positioning it was planned with."""

    positioning: str
    reasoning: str
    single: Plan
    # In posting order; empty when the Brief holds one idea.
    split: list[Plan]
    model: str
    usage: Optional[dict]


def plan_messages(brief: str, positioning: str, char_limit: int) -> list[dict]:
    cache_control = {"type": "ephemeral", "ttl": CACHE_TTL}
    prompt = plan_prompt(MAX_SPLIT_IDEAS, char_limit)
    return [
        {
            "role": "system",
            "content": [{"type": "text", "text": prompt, "cache_control": cache_control}],
        },
        {"role": "user", "content": plan_user(brief, positioning)},
    ]


def _text(value: str) -> str:
    return drop_unstorable(value).strip()


def _plan(planned: _Planned) -> Plan:
    """The Plan of one planned post. `one_line` and `few_lines` are short whatever `format` says."""
    length: Length = LENGTH_SHORT if planned.structure in _SHORT_STRUCTURES else planned.format
    return Plan(
        core_idea=_text(planned.core_idea),
        takeaway=_text(planned.takeaway),
        reasoning=_text(planned.reasoning),
        funnel=_FUNNELS[planned.funnel],
        desired_action=planned.desired_action,
        format=FORMAT_POST,
        length=length,
        structure=planned.structure,
    )


def _pulls(planned: _Planned, plan: Plan) -> list[str]:
    """Choices of one planned post that pull against each other. The Post is still written."""
    pulls = []
    if planned.format != plan.length:
        pulls.append(
            f"structure={plan.structure} is a short post: format={planned.format} is ignored "
            "and the post is planned short."
        )
    if plan.desired_action not in _FUNNEL_ACTIONS[plan.funnel]:
        fits = ", ".join(sorted(_FUNNEL_ACTIONS[plan.funnel]))
        pulls.append(
            f"desired_action={plan.desired_action} is unusual for the {plan.funnel} of the "
            f"funnel (usual: {fits})."
        )
    if plan.length == LENGTH_SHORT and plan.structure in (
        "hook_list_closer",
        "hook_playbook_closer",
    ):
        pulls.append(
            f"structure={plan.structure} in {SHORT_LIMIT} characters is tight: expect a very "
            "compressed list."
        )
    return pulls


def _plans(planned: Sequence[_Planned]) -> list[Plan]:
    plans = []
    for post in planned:
        plan = _plan(post)
        for pull in _pulls(post, plan):
            logger.warning("A plan's choices pull against each other: %s", pull)
        plans.append(plan)
    return plans


async def plan_brief(llm: LLM, brief: str, positioning: str, char_limit: int) -> PlannedBrief:
    """
    Plan `brief` for a User with this Positioning, whose X account's posts hold up to
    `char_limit` characters. Raises whatever the LLM port raises, and an `LLMError` when the
    call runs out of time; nothing is stored here.
    """
    response_model: type[Union[PostIdeas, ShortPostIdeas]] = (
        ShortPostIdeas if is_short_only(char_limit) else PostIdeas
    )
    try:
        async with asyncio.timeout(PLAN_CALL_SECONDS):
            result = await llm.structured(
                model=settings.LLM_PLANNING_MODEL,
                messages=plan_messages(brief, positioning, char_limit),
                response_model=response_model,
                max_tokens=MAX_TOKENS,
            )
    except TimeoutError as error:
        raise LLMError(
            f"{settings.LLM_PLANNING_MODEL}: the plan call took over {PLAN_CALL_SECONDS:.0f}s"
        ) from error
    ideas = result.parsed
    [single] = _plans([ideas.single_idea])
    split = _plans((ideas.split_ideas or [])[:MAX_SPLIT_IDEAS])
    return PlannedBrief(
        positioning=positioning,
        reasoning=_text(ideas.reasoning),
        single=single,
        # One split idea is no split: the single-post Idea already covers it.
        split=split if len(split) >= 2 else [],
        model=result.model,
        usage=result.usage.raw if result.usage else None,
    )
