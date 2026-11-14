from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pumpkit.core.text import drop_unstorable
from pumpkit.posts.formats import Format
from pumpkit.posts.media_files import cleaned_alt_text
from pumpkit.posts.models import MediaKind
from pumpkit.posts.plans import DesiredAction, Funnel, Length, Structure
from pumpkit.posts.writing.constants import BRIEF_MAX_CHARS, MAX_SPLIT_IDEAS
from pumpkit.posts.writing_state import WritingState

# Per caller, for the routes and MCP tools that write a Version.
WRITE_RATE = "20/minute"
# Per caller, for attaching Media: enough to drop four files on each Part of a Thread at once.
MEDIA_RATE = "60/minute"


class BriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The planner chooses the Format, so a Brief asks for a Thread in its own words.
    brief: str = Field(..., max_length=BRIEF_MAX_CHARS)

    @field_validator("brief")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = drop_unstorable(value).strip()
        if not stripped:
            raise ValueError("Write a brief first.")
        return stripped


class PartResponse(BaseModel):
    """One Part of a Version's text."""

    text: str
    # Counted by the backend the way the limit counts, which a browser's string length doesn't.
    char_count: int
    char_limit: int


class StartingTextResponse(BaseModel):
    """The Post's Text a Feedback was given on, when it differed from the Version before."""

    format: Format
    parts: list[PartResponse]
    # Whether the last Part is the single post's first reply.
    first_reply: bool
    version_number: int


class VersionResponse(BaseModel):
    id: str
    number: int
    # None for the first Version, which comes from the Brief.
    feedback: Optional[str]
    format: Format
    # The Version's text, one Part at a time, in order.
    parts: list[PartResponse]
    # Whether the last Part is the single post's first reply, posted as a reply to it.
    first_reply: bool
    starting_text: Optional[StartingTextResponse]
    created_at: datetime


class FailedFeedbackResponse(BaseModel):
    """Feedback whose Version Pumpkit couldn't write, as it was sent, to send again."""

    feedback: str
    format: Format


class MediaResponse(BaseModel):
    """One Media on a Part, as the web app and AI apps read it."""

    id: str
    kind: MediaKind
    # Under the API's root, served only to the Media's owner; None for a video sent without one.
    preview_url: Optional[str]
    width: Optional[int]
    height: Optional[int]
    # The image described for screen readers; None until the User or their AI app writes it.
    alt_text: Optional[str]
    # A video's length as the web app read it; None for images, GIFs and videos sent otherwise.
    duration_ms: Optional[int]


class AltTextRequest(BaseModel):
    """Alt text for one image or GIF; empty or null clears it."""

    alt_text: Optional[str]

    @field_validator("alt_text")
    @classmethod
    def _strip_and_limit(cls, value: Optional[str]) -> Optional[str]:
        return cleaned_alt_text(value)


class TextPartResponse(PartResponse):
    """One Part of a Post's Text, with the Media published with it, in order."""

    media: list[MediaResponse]


class TextResponse(BaseModel):
    """A Post's Text (ADR 0016)."""

    format: Format
    parts: list[TextPartResponse]
    # Whether the last Part is the single post's first reply, posted as a reply to it.
    first_reply: bool
    # The Version it came from: the last one written or restored.
    version_number: int
    edited: bool


class PlanResponse(BaseModel):
    """What Pumpkit decided about a Post before writing it."""

    core_idea: str
    takeaway: str
    # Who the Post is for: `top` for reach, `middle` for trust, `bottom` for conversion.
    funnel: Funnel
    desired_action: DesiredAction
    format: Format
    # None for a Thread.
    length: Optional[Length]
    structure: Structure


class PostResponse(BaseModel):
    id: str
    brief: str
    # None for a Post written before Briefs were planned.
    plan: Optional[PlanResponse]
    versions: list[VersionResponse]
    # "writing" while its first Version is written in the background, then None.
    writing_state: Optional[WritingState]


class WriteIdeasRequest(BaseModel):
    """The Ideas of a Brief to write, each as a Post of its own."""

    model_config = ConfigDict(extra="forbid")

    # Split Ideas or the single-post one. Empty is refused with a reason the page can show.
    idea_ids: list[str] = Field(..., max_length=MAX_SPLIT_IDEAS + 1)

    @field_validator("idea_ids")
    @classmethod
    def _once_each(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class BriefPostResponse(BaseModel):
    """An Idea's Post as its Brief's page shows it."""

    id: str
    # "writing" while its first Version is written, "not_written" when Pumpkit couldn't write it.
    writing_state: Optional[WritingState]
    # None until its first Version is written.
    text: Optional[TextResponse]


class IdeaResponse(BaseModel):
    id: str
    # Where the Idea comes among the Ideas posted with it, from 1; the single-post Idea is 1.
    posting_order: int
    # True for the single-post Idea, which covers the whole Brief.
    whole_brief: bool
    plan: Optional[PlanResponse]
    # None until the User writes the Idea.
    post: Optional[BriefPostResponse]


class BriefResponse(BaseModel):
    id: str
    text: str
    created_at: datetime
    # The single-post Idea first, then the split Ideas in posting order.
    ideas: list[IdeaResponse]
    # The Posts the User can still have written, Top-ups included and writes in progress taken
    # out, as writing the Ideas checks it; None with no cap on Generations.
    generations_left: Optional[int]
