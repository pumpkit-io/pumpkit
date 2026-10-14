"""Naming the Community a Scheduled post goes to: the ID read from what the User pasted."""

import re
from dataclasses import dataclass
from typing import Optional

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


@dataclass(frozen=True)
class Community:
    id: str
    # As the User saw it when they picked it; None when it couldn't be looked up.
    name: Optional[str]


def community_url(community_id: str) -> str:
    return f"https://x.com/i/communities/{community_id}"


def check_community_id(community_id: str) -> str:
    """The ID as given when it fits X's pattern; anything else is a `RuleBroken`."""
    if not _BARE_ID.fullmatch(community_id):
        raise RuleBroken(NOT_A_COMMUNITY)
    return community_id


def community_id_from(pasted: str) -> str:
    """The Community ID in a pasted Community URL or bare ID; anything else is a `RuleBroken`."""
    pasted = pasted.strip()
    if _BARE_ID.fullmatch(pasted):
        return pasted
    url = _URL.fullmatch(pasted)
    if url is None:
        raise RuleBroken(NOT_A_COMMUNITY)
    return url.group("id")
