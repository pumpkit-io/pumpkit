"""Naming the Community a Scheduled post goes to: the ID read from what the User pasted."""

import re

from pumpkit.scheduling.rules import RuleBroken

NOT_A_COMMUNITY = (
    "That isn't a Community. Paste its URL from X, like https://x.com/i/communities/123, or its ID."
)

# X's pattern for a Community ID.
_ID = r"\d{1,19}"
_BARE_ID = re.compile(_ID)
_URL = re.compile(
    rf"(?:https?://)?(?:www\.)?(?:x|twitter)\.com/i/communities/(?P<id>{_ID})/?(?:\?\S*)?",
    re.IGNORECASE,
)


def community_id_from(pasted: str) -> str:
    """The Community ID in a pasted Community URL or bare ID; anything else is a `RuleBroken`."""
    pasted = pasted.strip()
    if _BARE_ID.fullmatch(pasted):
        return pasted
    url = _URL.fullmatch(pasted)
    if url is None:
        raise RuleBroken(NOT_A_COMMUNITY)
    return url.group("id")
