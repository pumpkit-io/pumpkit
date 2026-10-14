from datetime import datetime
from typing import Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from pumpkit.scheduling.models import ScheduledPostState

# Bounds the work of counting (about 2s at worst), with room for long URLs in a 25,000 post.
SCHEDULED_POST_TEXT_MAX_CHARS = 30_000
# Far past any Community name X allows; the name is only a label the User sees.
COMMUNITY_NAME_MAX_CHARS = 200
COMMUNITY_PASTE_MAX_CHARS = 2_000


def _strip_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("Write the post first.")
    return stripped


class CommunityRequest(BaseModel):
    """A Community as the client named it: the server checks the ID and trusts the name."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: Optional[str] = Field(None, max_length=COMMUNITY_NAME_MAX_CHARS)


class CommunityLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A Community URL or bare ID as the User pasted it.
    pasted: str = Field(..., max_length=COMMUNITY_PASTE_MAX_CHARS)


class CommunityResponse(BaseModel):
    id: str
    # None when it couldn't be looked up: show the ID instead.
    name: Optional[str]
    url: str


class ScheduledPostCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., max_length=SCHEDULED_POST_TEXT_MAX_CHARS)
    # Exactly one of the two: a time with its UTC offset, or publish within the request.
    publish_at: Optional[AwareDatetime] = None
    publish_now: bool = False
    # The Version whose Final the text copies; None for a typed post.
    source_version_id: Optional[str] = None
    # The Community it goes to; None for the User's profile.
    community: Optional[CommunityRequest] = None
    # With a Community, whether X also shares it with the account's followers; ignored without.
    share_with_followers: bool = False

    _strip = field_validator("text")(_strip_text)

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
    # The Version whose Final it copied; None when typed or when that Version is gone.
    source_version_id: Optional[str]
    # The Community it goes to; None for the User's profile.
    community: Optional[CommunityResponse]
    share_with_followers: bool
    created_at: datetime


class ScheduledPostsListResponse(BaseModel):
    data: list[ScheduledPostResponse]


class ScheduledPostUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Optional[str] = Field(None, max_length=SCHEDULED_POST_TEXT_MAX_CHARS)
    # A new time reschedules the Scheduled post on the X account connected now.
    publish_at: Optional[AwareDatetime] = None

    _strip = field_validator("text")(_strip_text)

    @model_validator(mode="after")
    def _something_to_change(self) -> "ScheduledPostUpdateRequest":
        if self.text is None and self.publish_at is None:
            raise ValueError("Give a new text, a new publish time, or both.")
        return self


class XConnectionResponse(BaseModel):
    """The User's X connection. Tokens never leave the backend."""

    handle: str
    # The longest Scheduled post X accepts from this account, in X's weighted characters.
    char_limit: int
    needs_reconnect: bool
    # Scheduled posts for this X account not yet published; disconnecting makes them fail.
    scheduled_posts_waiting: int
