from datetime import datetime
from typing import Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models import ScheduledPostState

# Far above any limit X applies by its own count; it bounds the work of counting.
SCHEDULED_POST_TEXT_MAX_CHARS = 25_000


class ScheduledPostCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., max_length=SCHEDULED_POST_TEXT_MAX_CHARS)
    # Exactly one of the two: a time with its UTC offset, or publish within the request.
    publish_at: Optional[AwareDatetime] = None
    publish_now: bool = False

    @field_validator("text")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Write the post first.")
        return stripped

    @model_validator(mode="after")
    def _one_time(self) -> "ScheduledPostCreateRequest":
        if (self.publish_at is None) == (not self.publish_now):
            raise ValueError("Give either a publish time or publish now, not both.")
        return self


class ScheduledPostResponse(BaseModel):
    id: str
    text: str
    state: ScheduledPostState
    publish_at: datetime
    published_at: Optional[datetime]
    # The post on X, once Published.
    x_post_url: Optional[str]
    # Why it Failed, in words for the User.
    failed_reason: Optional[str]
    created_at: datetime


class ScheduledPostsListResponse(BaseModel):
    data: list[ScheduledPostResponse]


class ScheduledPostUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Optional[str] = Field(None, max_length=SCHEDULED_POST_TEXT_MAX_CHARS)
    # A new time reschedules the Scheduled post on the X account connected now.
    publish_at: Optional[AwareDatetime] = None

    @field_validator("text")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Write the post first.")
        return stripped

    @model_validator(mode="after")
    def _something_to_change(self) -> "ScheduledPostUpdateRequest":
        if self.text is None and self.publish_at is None:
            raise ValueError("Give a new text, a new publish time, or both.")
        return self
