"""Naming the Community a Scheduled post goes to: the ID read from what the User pasted."""

import re
from dataclasses import dataclass
from typing import Optional

from pumpkit.scheduling.rules import RuleBroken

NOT_A_COMMUNITY = (
    "That isn't a Community. Paste its URL from X, like https://x.com/i/communities/123, or its ID."
)

# X's pattern for a Community ID.
_ID = r"[0-9]{1,19}"
_BARE_ID = re.compile(_ID)
_URL = re.compile(
    rf"(?:https?://)?(?:www\.)?(?:x|twitter)\.com/i/communities/(?P<id>{_ID})/?(?:\?\S*)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Community:
    id: str
    # As Pumpkit looked it up on X; None when it couldn't be.
    name: Optional[str]


@dataclass(frozen=True)
class Destination:
    # None for the User's profile.
    community: Optional[Community] = None
    # Whether X also shares it with the account's followers; counts only with a Community.
    share_with_followers: bool = False


def community_url(community_id: str) -> str:
    return f"https://x.com/i/communities/{community_id}"


def community_id_from(pasted: str) -> str:
    """The Community ID in a pasted Community URL or bare ID; anything else is a `RuleBroken`."""
    pasted = pasted.strip()
    if _BARE_ID.fullmatch(pasted):
        return pasted
    url = _URL.fullmatch(pasted)
    if url is None:
        raise RuleBroken(NOT_A_COMMUNITY)
    return url.group("id")
