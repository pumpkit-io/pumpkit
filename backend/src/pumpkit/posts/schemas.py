from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pumpkit.posts.formats import FORMAT_POST, Format
from pumpkit.posts.writing.constants import BRIEF_MAX_CHARS, FEEDBACK_MAX_CHARS

# Per caller, for the routes and MCP tools that write a Version.
WRITE_RATE = "20/minute"


class PostStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: str = Field(..., max_length=BRIEF_MAX_CHARS)
    format: Format = FORMAT_POST

    @field_validator("brief")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Write a Brief first.")
        return stripped


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: str = Field(..., max_length=FEEDBACK_MAX_CHARS)
    # None keeps the latest Version's Format.
    format: Optional[Format] = None

    @field_validator("feedback")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Write some Feedback first.")
        return stripped


class TellResponse(BaseModel):
    name: str
    description: str


class PartResponse(BaseModel):
    """One Part of a Final."""

    text: str
    # Counted by the backend the way the limit counts, which a browser's string length doesn't.
    char_count: int
    char_limit: int


class VersionResponse(BaseModel):
    id: str
    number: int
    # None for the first Version, which comes from the Brief.
    feedback: Optional[str]
    format: Format
    draft_parts: list[str]
    # The Final's Parts in order.
    parts: list[PartResponse]
    # What the slop check found in any Part of the Final, for the User to judge.
    tells: list[TellResponse]


class PostResponse(BaseModel):
    id: str
    brief: str
    versions: list[VersionResponse]


class VersionToolResponse(BaseModel):
    """A Version as the MCP tools answer with it: no Draft, which only the web app shows."""

    id: str
    number: int
    feedback: Optional[str]
    format: Format
    parts: list[PartResponse]


class PostToolResponse(BaseModel):
    id: str
    brief: str
    versions: list[VersionToolResponse]


MAX_POSTS_PAGE_SIZE = 50


class PostsPageRequest(BaseModel):
    limit: int = Field(20, ge=1, le=MAX_POSTS_PAGE_SIZE)
    offset: int = Field(0, ge=0)


class PostSummaryResponse(BaseModel):
    id: str
    brief: str
    created_at: datetime
    version_count: int


class PostsPageResponse(BaseModel):
    data: list[PostSummaryResponse]
    # The offset of the next page, or None on the last one.
    next_offset: Optional[int]
