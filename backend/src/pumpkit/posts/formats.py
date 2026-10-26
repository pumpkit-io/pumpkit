"""A Version's Format, and how each of its Parts is counted against its limit."""

from collections.abc import Sized
from typing import Literal, Optional

from pumpkit.posts.writing.constants import POST_MAX_CHARS
from pumpkit.x_connection.x_length import X_POST_MAX_CHARS, x_weighted_length

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
    """How a message names Part `number`: "Part 3" in a Thread, None in a single post."""
    return f"Part {number}" if part_count > 1 else None


def part_char_count(format: Format, text: str) -> int:
    if format == FORMAT_THREAD:
        return x_weighted_length(text)
    # Code points, as pumpkit-v6 counted against the limit the draft prompt states.
    return len(text)


def part_char_limit(format: Format) -> int:
    """A Thread's Parts are written to fit any X account, so they get X's default limit."""
    if format == FORMAT_THREAD:
        return X_POST_MAX_CHARS
    return POST_MAX_CHARS
