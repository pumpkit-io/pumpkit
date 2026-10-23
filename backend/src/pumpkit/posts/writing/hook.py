"""
The hook call's answer and the check it passes before its Hook goes to the draft call. The
Hook is written first and the draft call is told to start the post with it.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict

from pumpkit.posts.writing.constants import POST_MAX_CHARS
from pumpkit.posts.writing.prompts.hook import HOOK_NAMES


class WrittenHook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook_name: Optional[str]
    hook: Optional[str]


# The SDK sends the class name as the schema name, snake_case like v6's schemas.
WrittenHook.__name__ = "written_hook"


class HookRefused(Exception):
    """The answer can't be used; the draft call gets no Hook."""


def usable_hook(answer: WrittenHook) -> Optional[str]:
    """
    The answer's Hook without surrounding whitespace, or None when the hook call chose to write
    none. Raises `HookRefused` when the answer can't be used.
    """
    if answer.hook_name is None and answer.hook is None:
        return None
    if answer.hook_name not in HOOK_NAMES:
        raise HookRefused(f"unknown hook {answer.hook_name!r}")
    hook = (answer.hook or "").strip()
    if not hook:
        raise HookRefused("the answer names a hook but writes none")
    # Code points, as the Final is counted against the same limit.
    if len(hook) >= POST_MAX_CHARS:
        raise HookRefused(f"the Hook is {len(hook)} characters")
    return hook
