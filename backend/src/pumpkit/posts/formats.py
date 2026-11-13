"""A Version's Format: a single X post or a Thread."""

from collections.abc import Sized
from typing import Literal, Optional

Format = Literal["post", "thread"]
FORMAT_POST: Format = "post"
FORMAT_THREAD: Format = "thread"


def format_of(parts: Sized, *, first_reply: bool) -> Format:
    """Parts with no Format of their own, as a Scheduled post's: a first reply keeps them a post."""
    return FORMAT_THREAD if len(parts) > 1 and not first_reply else FORMAT_POST


def format_noun(format: Format) -> str:
    """The word a prompt uses for a text in this Format."""
    return "thread" if format == FORMAT_THREAD else "post"


def part_name(number: int, part_count: int, *, first_reply: bool) -> Optional[str]:
    """Part `number` mid-sentence: "part 3", "the post", "the first reply", or None if alone."""
    if first_reply:
        return "the first reply" if number == part_count else "the post"
    return f"part {number}" if part_count > 1 else None
