"""
Splicing the hook call's answer into the Draft. Code does the splice, not the model, so every
character after the Hook stays as the draft call wrote it.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from pumpkit.posts.writing.constants import POST_MAX_CHARS
from pumpkit.posts.writing.prompts.hook import HOOK_NAMES

NO_HOOK = "none"

# The prompt tells the model a prepended Hook sits one blank line above the Draft.
PREPEND_SEPARATOR = "\n\n"


class HookedPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook_name: str
    mode: Literal["keep", "replace", "prepend"]
    replaced_opening: str
    hook: str


HookedPost.__name__ = "hooked_post"


class HookRefused(Exception):
    """The answer can't be spliced; the Draft goes on without a Hook."""


def splice(draft: str, answer: HookedPost) -> str:
    """The Draft with the answer's Hook in it. Raises `HookRefused` when the answer can't be used."""
    if answer.hook_name != NO_HOOK and answer.hook_name not in HOOK_NAMES:
        raise HookRefused(f"unknown hook {answer.hook_name!r}")
    if answer.mode == "keep":
        return draft
    if answer.hook_name == NO_HOOK:
        raise HookRefused(f"hook_name 'none' with mode {answer.mode!r}")
    hook = answer.hook.rstrip()
    if not hook.strip():
        raise HookRefused(f"blank hook with mode {answer.mode!r}")
    if answer.mode == "prepend":
        hooked = hook + PREPEND_SEPARATOR + draft
    elif answer.replaced_opening and draft.startswith(answer.replaced_opening):
        hooked = hook + draft[len(answer.replaced_opening) :]
    else:
        raise HookRefused("replaced_opening is not a prefix of the Draft")
    # Code points, as the Final is counted against the same limit.
    if len(hooked) > POST_MAX_CHARS:
        raise HookRefused(f"the hooked Draft is {len(hooked)} characters")
    return hooked
