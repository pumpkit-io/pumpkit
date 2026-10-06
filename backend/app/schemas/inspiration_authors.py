from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.x_handles import normalize_handle


class InspirationAuthorAddRequest(BaseModel):
    """An X handle, with or without the @; it is normalised on the way in."""

    model_config = ConfigDict(extra="forbid")

    handle: str = Field(..., max_length=64)

    @field_validator("handle")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_handle(value)


class InspirationAuthorResponse(BaseModel):
    handle: str
    # None only if the handle has no fetch record, which adding an author always writes.
    last_fetched_at: Optional[datetime]
    post_count: int


class InspirationAuthorsListResponse(BaseModel):
    """The User's Inspiration authors in the order they were added."""

    data: list[InspirationAuthorResponse]
