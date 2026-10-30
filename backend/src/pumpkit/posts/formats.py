"""A Version's Format: a single X post or a Thread."""

from collections.abc import Sized
from typing import Literal, Optional

Format = Literal["post", "thread"]
FORMAT_POST: Format = "post"
FORMAT_THREAD: Format = "thread"


def format_of(parts: Sized) -> Format:
    """One Part is a single post; several are a Thread."""
    return FORMAT_THREAD if len(parts) > 1 else FORMAT_POST


def format_noun(format: Format) -> str:
    """The word a prompt uses for a text in this Format."""
    return "thread" if format == FORMAT_THREAD else "post"


def part_name(number: int, part_count: int) -> Optional[str]:
    """How a message names Part `number` mid-sentence: "part 3" in a Thread, None in a single post."""
    return f"part {number}" if part_count > 1 else None
