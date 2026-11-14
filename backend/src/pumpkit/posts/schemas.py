from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pumpkit.posts.formats import FORMAT_POST, Format
from pumpkit.posts.media_files import cleaned_alt_text
from pumpkit.posts.models import MediaKind
from pumpkit.posts.plans import DesiredAction, Funnel, Length, Structure
from pumpkit.posts.writing.constants import BRIEF_MAX_CHARS

# Per caller, for the routes and MCP tools that write a Version.
WRITE_RATE = "20/minute"
# Per caller, for attaching Media: enough to drop four files on each Part of a Thread at once.
MEDIA_RATE = "60/minute"


class PostStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: str = Field(..., max_length=BRIEF_MAX_CHARS)
    format: Format = FORMAT_POST

    @field_validator("brief")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
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
