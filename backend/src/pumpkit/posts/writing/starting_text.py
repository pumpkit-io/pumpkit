"""
The Starting text (ADR 0016): the Post's Text a Feedback was given on, when it differs from the
Version before, and the sentences the User wrote into it by hand.
"""

import re
from dataclasses import dataclass
from typing import Optional

from pumpkit.posts.formats import Format


@dataclass(frozen=True)
class StartingText:
    format: Format
    parts: list[str]
    # The Version the Text came from, the last one written or restored before the Feedback.
    version_number: int
    # Whether the last of `parts` is a single post's first reply (ADR 0027).
    first_reply: bool


def starting_text(
    text: StartingText,
    previous_format: Format,
    previous_parts: list[str],
    previous_first_reply: bool,
) -> Optional[StartingText]:
    """The Text as a Starting text, or None when it is the Version before as written."""
    if (text.format, text.parts, text.first_reply) == (
        previous_format,
        previous_parts,
        previous_first_reply,
    ):
        return None
    return text


# A sentence ends at its closing punctuation before a space, or at a line break.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?…])\s+|\s*\n\s*")


def _sentences(parts: list[str]) -> list[str]:
    return [
        sentence.strip()
        for part in parts
        for sentence in _SENTENCE_BREAK.split(part)
        if sentence.strip()
    ]


_PUNCTUATION = re.compile(r"[^\w\s]")


def _words(sentence: str) -> str:
    return " ".join(_PUNCTUATION.sub("", sentence).casefold().split())


def hand_written_sentences(starting: StartingText, began_from: list[str]) -> list[str]:
    """
    The Starting text's sentences that the Version it began from doesn't have, in order: what the
    User typed or reworded. A sentence moved, or changed only in punctuation or case, isn't one.
    """
    written = {_words(sentence) for sentence in _sentences(began_from)}
    found: list[str] = []
    for sentence in _sentences(starting.parts):
        if _words(sentence) not in written and sentence not in found:
            found.append(sentence)
    return found
