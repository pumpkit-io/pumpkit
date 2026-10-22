"""
Splicing the hook call's answer into the Draft. Code does the splice, not the model, so every
character after the Hook stays as the draft call wrote it.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from pumpkit.posts.writing.constants import POST_MAX_CHARS
from pumpkit.posts.writing.prompts.hook import HOOK_NAMES

# The prompt tells the model a prepended Hook sits one blank line above the Draft.
PREPEND_SEPARATOR = "\n\n"


class HookedPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_hook_name: Optional[str]
    mode: Literal["keep", "replace", "prepend"]
    replacing_hook_name: Optional[str]
    replaced_opening: Optional[str]
    hook: Optional[str]


# The SDK sends the class name as the schema name, snake_case like v6's schemas.
HookedPost.__name__ = "hooked_post"


class HookRefused(Exception):
    """The answer can't be spliced; the Draft goes on without a Hook."""


def splice(draft: str, answer: HookedPost) -> str:
    """The Draft with the answer's Hook in it. Raises `HookRefused` when the answer can't be used."""
    if answer.current_hook_name is not None and answer.current_hook_name not in HOOK_NAMES:
        raise HookRefused(f"unknown current hook {answer.current_hook_name!r}")
    if answer.mode == "keep":
        return draft
    if answer.replacing_hook_name not in HOOK_NAMES:
        raise HookRefused(f"unknown replacing hook {answer.replacing_hook_name!r}")
    hook = (answer.hook or "").rstrip()
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
