from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pumpkit.authors.handles import normalize_handle

# Per caller, for the routes and MCP tools that add, refresh or remove Inspiration authors.
WRITE_RATE = "20/minute"


class InspirationAuthorAddRequest(BaseModel):
    """An X handle, with or without the @; it is normalised on the way in."""

    model_config = ConfigDict(extra="forbid")

    handle: str = Field(..., max_length=64)

    @field_validator("handle")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_handle(value)


class InspirationAuthorToolResponse(BaseModel):
    """An Inspiration author as the MCP tools answer with it: without its photo."""

    handle: str
    # None only if the handle has no fetch record, which adding an author always writes.
    last_fetched_at: Optional[datetime]
    post_count: int


class InspirationAuthorResponse(InspirationAuthorToolResponse):
    # The author's name and X's URL for their photo, from the Author directory.
    name: Optional[str]
    photo_url: Optional[str]


class InspirationAuthorsListToolResponse(BaseModel):
    """The User's Inspiration authors in the order they were added."""

    data: list[InspirationAuthorToolResponse]


class InspirationAuthorsListResponse(BaseModel):
    """The User's Inspiration authors in the order they were added."""

    data: list[InspirationAuthorResponse]


class AuthorDirectoryEntryResponse(BaseModel):
    handle: str
    name: Optional[str]
    photo_url: Optional[str]
    # How many Users of the Instance have it in their Persona, never which ones.
    persona_count: int


class AuthorDirectoryResponse(BaseModel):
    """Every account in the Author directory, by handle."""

    data: list[AuthorDirectoryEntryResponse]
