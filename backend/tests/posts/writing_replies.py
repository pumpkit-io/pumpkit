"""The sketch and revision calls' scripted replies, for tests that write a Version."""

from typing import Optional

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
