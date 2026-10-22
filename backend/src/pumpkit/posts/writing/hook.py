"""
Splicing the hook call's answer into the Draft. Code does the splice, not the model, so every
character after the Hook stays as the draft call wrote it.

The model writes the Hook followed by the lines it carries over unchanged, so it sees what the
Hook leads into.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from pumpkit.posts.writing.constants import POST_MAX_CHARS
from pumpkit.posts.writing.prompts.hook import HOOK_NAMES


class HookedPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_hook_name: Optional[str]
    mode: Literal["keep", "replace"]
    replacing_hook_name: Optional[str]
    replaced_text: Optional[str]
    replacing_text: Optional[str]


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
    replaced = answer.replaced_text or ""
    replacing = answer.replacing_text or ""
    if not replaced or not draft.startswith(replaced):
        raise HookRefused("replaced_text is not a prefix of the Draft")
    rest = draft[len(replaced) :]
    if replaced.endswith("\n") or (rest and not rest.startswith("\n")):
        raise HookRefused("replaced_text does not end at a line break")
    if not _hook_then_carried_lines(replaced, replacing):
        raise HookRefused("replacing_text does not end with a Hook and the lines carried over")
    hooked = replacing + rest
    # Code points, as the Final is counted against the same limit.
    if len(hooked) > POST_MAX_CHARS:
        raise HookRefused(f"the hooked Draft is {len(hooked)} characters")
    return hooked


def _hook_then_carried_lines(replaced: str, replacing: str) -> bool:
    """
    Whether both texts end with the same whole lines, at least one of them non-blank, and
    `replacing` opens with a Hook on lines of its own, then a line break or one blank line.
    """
    starts = [0] + [i + 1 for i, char in enumerate(replaced) if char == "\n"]
    for start in starts:
        carried = replaced[start:]
        if not carried.strip() or not replacing.endswith(carried):
            continue
        hook = replacing[: len(replacing) - len(carried)]
        text = hook.strip()
        if text and hook in (text + "\n", text + "\n\n"):
            return True
    return False
