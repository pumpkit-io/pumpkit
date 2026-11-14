"""The plan, sketch and revision calls' scripted replies, for tests that write a Version."""

from typing import Optional

# The schema name of the plan call's answer, which `fake_llm.standing` keys its reply by.
POST_IDEAS = "post_ideas"


def planned_post(
    core_idea: str = "Shipping small things beats planning big ones.", **choices
) -> dict:
    """One planned post as the plan call answers it: a short trust post by default, which any account takes."""
    return {
        "core_idea": core_idea,
        "takeaway": "Ship the smallest thing that works this week.",
        "reasoning": "The brief holds one result with its numbers, which earns trust.",
        "funnel": "MOF",
        "desired_action": "bookmark",
        "format": "short",
        "structure": "few_lines",
        **choices,
    }


# The default `planned_post()` as a Post's response shows its Plan.
PLAN = {
    "core_idea": "Shipping small things beats planning big ones.",
    "takeaway": "Ship the smallest thing that works this week.",
    "funnel": "middle",
    "desired_action": "bookmark",
    "format": "post",
    "length": "short",
    "structure": "few_lines",
}


def ideas(single: Optional[dict] = None, split: Optional[list[dict]] = None) -> dict:
    """The plan call's answer: the single-post plan, and the split plans when there are any."""
    return {
        "reasoning": "The brief holds one idea, so there is no split.",
        "single_idea": single or planned_post(),
        "split_ideas": split,
    }


REASONING = (
    "The brief is a plain observation, so a natural opening fits better than a library hook."
)


def written(post: str, hook_name: Optional[str] = None, hook_reasoning: str = REASONING) -> dict:
    """The writing call's answer, opening with no library Hook unless `hook_name` names one."""
    return {"hook_reasoning": hook_reasoning, "hook_name": hook_name, "post": post}


def written_thread(
    parts: list[str], hook_name: Optional[str] = None, hook_reasoning: str = REASONING
) -> dict:
    """The Thread writing call's answer, its Parts in order."""
    return {"hook_reasoning": hook_reasoning, "hook_name": hook_name, "parts": parts}


def writing_calls(fake_llm) -> list:
    """The calls the fake model received after the plan call: the ones that wrote a Version."""
    return [call for call in fake_llm.calls if call.response_model.__name__ != POST_IDEAS]
