"""
Replace the characters that give a post away as pasted from a model, ported from pumpkit-v6.

Each one (an em or en dash, a curly quote, an ellipsis character, an arrow, a typed bullet,
a multiplication sign, an invisible space) has exactly one typed replacement, so it is swapped
in code between the draft call and the humanizer call rather than asked of a model.
"""

import re

# One character to one string. Left and right arrows only: "↑" and "↓" have no
# typed equivalent anyone would use, so they stay for a person to judge.
REPLACEMENTS = {
    # An en dash is swapped where it stands, spacing untouched: "4–5" is a
    # range and must stay tight. Only the em dash gets spaces (below).
    "–": "-",
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    "→": "->",
    "⇒": "->",
    "←": "<-",
    "•": "-",
    "×": "x",
    # A non-breaking space becomes an ordinary one rather than nothing, because
    # it usually sits between two words and deleting it would join them.
    "\u00a0": " ",
    # Zero-width characters are removed outright - there is nothing to keep.
    "\u200b": "",
    "\u200c": "",
    "\u200d": "",
    "\ufeff": "",
}

_TABLE = str.maketrans(REPLACEMENTS)

# An em dash gets a space only on a side that touches a word, so a spaced dash
# isn't spaced twice: "this—that" becomes "this - that".
_SPACE_BEFORE = re.compile(r"(?<=\w)—")
_SPACE_AFTER = re.compile(r"—(?=\w)")


def scrub(text: str) -> str:
    """Return `text` with every character in REPLACEMENTS and every em dash
    replaced by its typed equivalent."""
    text = text.translate(_TABLE)
    text = _SPACE_BEFORE.sub(" —", text)
    text = _SPACE_AFTER.sub("— ", text)
    return text.replace("—", "-")
