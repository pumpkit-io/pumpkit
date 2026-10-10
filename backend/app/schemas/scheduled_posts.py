from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import ScheduledPostState

# Far above any limit X applies by its own count; it bounds the work of counting.
SCHEDULED_POST_TEXT_MAX_CHARS = 25_000


class ScheduledPostCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., max_length=SCHEDULED_POST_TEXT_MAX_CHARS)
    # TODO(#62): take a publish time instead; until then a Scheduled post is published now.
    publish_now: Literal[True]

    @field_validator("text")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Write the post first.")
        return stripped


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
