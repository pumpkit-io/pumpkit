"""What the draft of a Positioning is made from, and what is kept of the model's answer."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional, Sequence

from pydantic import BaseModel, Field

from pumpkit.core.text import drop_unstorable
from pumpkit.positioning.draft_prompt import DRAFT_PROMPT
from pumpkit.positioning.schemas import POSITIONING_MAX_CHARS

# Each draft is a paid twitterapi.io call and a model call, so a User gets this many a day.
DRAFTS_PER_DAY = 5
DRAFT_WINDOW = timedelta(days=1)

# One page of the X reader, which is as many posts as one paid call returns.
DRAFT_POSTS = 20


@dataclass(frozen=True)
class XProfile:
    """What a User's X profile says about them; a field is None when they left it blank."""

    handle: str
    bio: Optional[str]
    location: Optional[str]
    website: Optional[str]

    def is_blank(self) -> bool:
        return self.bio is None and self.location is None and self.website is None


class PositioningDraft(BaseModel):
    """The model's answer to the draft call."""

    positioning: str = Field(description="Three to five first-person sentences, in one paragraph.")


def draft_messages(profile: XProfile, posts: Sequence[str]) -> list[dict]:
    """The draft call's messages: the prompt, then the profile and the posts, newest first."""
    fields = [
        ("Handle", f"@{profile.handle}"),
        ("Bio", profile.bio),
        ("Location", profile.location),
        ("Website", profile.website),
    ]
    lines = [f"{label}: {value}" for label, value in fields if value is not None]
    blocks = ["\n".join(["<profile>", *lines, "</profile>"])]
    if posts:
        tagged = [f"<post>\n{post}\n</post>" for post in posts]
        blocks.append("\n".join(["<posts>", *tagged, "</posts>"]))
    return [
        {"role": "system", "content": DRAFT_PROMPT},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]


def post_texts(texts: Sequence[str]) -> list[str]:
    """The newest `DRAFT_POSTS` of `texts`, given newest first, as the model can be sent them."""
    cleaned = (drop_unstorable(text).strip() for text in texts[:DRAFT_POSTS])
    return [text for text in cleaned if text]


def draft_text(answer: PositioningDraft) -> Optional[str]:
    """The model's draft as a Positioning could be saved; None when it wrote nothing."""
    text = drop_unstorable(answer.positioning).strip()
    return text[:POSITIONING_MAX_CHARS].rstrip() or None
