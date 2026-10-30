from datetime import datetime
from typing import Annotated, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from pumpkit.posts.formats import Format, part_name
from pumpkit.posts.schemas import TextResponse, VersionResponse
from pumpkit.posts.writing.constants import FEEDBACK_MAX_CHARS
from pumpkit.scheduling.models import ScheduledPostState
from pumpkit.scheduling.post_status import PostStatus

# Bounds the work of counting (about 2s at worst), with room for long URLs in a 25,000 post.
SCHEDULED_POST_TEXT_MAX_CHARS = 30_000
# Bounds the work of counting a whole Scheduled post, well above any Thread worth publishing.
SCHEDULED_POST_MAX_PARTS = 25
COMMUNITY_PASTE_MAX_CHARS = 2_000

PartText = Annotated[str, StringConstraints(max_length=SCHEDULED_POST_TEXT_MAX_CHARS)]
Parts = Annotated[list[PartText], Field(min_length=1, max_length=SCHEDULED_POST_MAX_PARTS)]


def _strip_parts(value: Optional[list[str]]) -> Optional[list[str]]:
    if value is None:
        return None
    stripped = [part.strip() for part in value]
    for number, part in enumerate(stripped, start=1):
        if not part:
            name = part_name(number, len(stripped))
            raise ValueError(f"Write {name} first." if name else "Write the post first.")
    return stripped


# Per caller, for the create route and the MCP tools that change Scheduled posts.
WRITE_RATE = "10/minute"


class CommunityLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A Community URL or bare ID as the User pasted it.
    pasted: str = Field(..., max_length=COMMUNITY_PASTE_MAX_CHARS)


class CommunityResponse(BaseModel):
    id: str
    # None when it couldn't be looked up: show the ID instead.
    name: Optional[str]
    url: str


class PastCommunitiesResponse(BaseModel):
    """The Communities the User posted to before on the connected X account, most recent first."""

    data: list[CommunityResponse]


class ScheduledPostCreateRequest(BaseModel):
    """`rules.NewScheduledPost` checks which fields go together."""

    model_config = ConfigDict(extra="forbid")

    # The Post whose Text the server copies: a Scheduled post is never typed (ADR 0015, 0016).
    post_id: str
    # A time with its UTC offset, or else publish within the request.
    publish_at: Optional[AwareDatetime] = None
    publish_now: bool = False
    # The ID or URL of the Community it goes to; None for the User's profile.
    community: Optional[str] = Field(None, max_length=COMMUNITY_PASTE_MAX_CHARS)
    # With a Community, whether X also shares it with the account's followers; ignored without.
    share_with_followers: bool = False


class ScheduledPostPartResponse(BaseModel):
    text: str
    # Whether X has accepted this Part.
    live: bool
    # This Part on X, once live.
    x_post_url: Optional[str]


class ScheduledPostResponse(BaseModel):
    id: str
    # In the order they go out; one Part is a single X post.
    parts: list[ScheduledPostPartResponse]
    state: ScheduledPostState
    publish_at: datetime
    published_at: Optional[datetime]
    # The first Part on X, once Published.
    x_post_url: Optional[str]
    # Why it Failed, in words for the User.
    failed_reason: Optional[str]
    # The Post whose Text it copied.
    post_id: str
    # The Community it goes to; None for the User's profile.
    community: Optional[CommunityResponse]
    share_with_followers: bool
    created_at: datetime


class PostDetailResponse(BaseModel):
    """One Post with its Text, its Versions in order, and the status its Scheduled post gives it."""

    id: str
    brief: str
    # None only for a Post whose first Version failed.
    text: Optional[TextResponse]
    versions: list[VersionResponse]
    status: PostStatus
    # None while the Post is a Draft.
    scheduled_post: Optional[ScheduledPostResponse]


MAX_POSTS_PAGE_SIZE = 50


class PostsPageRequest(BaseModel):
    # None lists every Post, the newest Version first.
    status: Optional[PostStatus] = None
    limit: int = Field(20, ge=1, le=MAX_POSTS_PAGE_SIZE)
    offset: int = Field(0, ge=0)


class ScheduledPostSummaryResponse(BaseModel):
    """What a listed Post shows of its Scheduled post; `GET /posts/{id}` has the rest."""

    id: str
    state: ScheduledPostState
    publish_at: datetime
    published_at: Optional[datetime]
    # The Community it goes to; None for the User's profile.
    community: Optional[CommunityResponse]
    share_with_followers: bool
    failed_reason: Optional[str]
    # The first Part on X, once it is live.
    x_post_url: Optional[str]


class PostListItemResponse(BaseModel):
    id: str
    brief: str
    status: PostStatus
    # The Scheduled post's text when it has one, else the latest Version's; the first Part's
    # first line is the Post's title.
    parts: list[str]
    format: Format
    version_count: int
    latest_version_at: datetime
    scheduled_post: Optional[ScheduledPostSummaryResponse]


class PostCountsResponse(BaseModel):
    draft: int
    scheduled: int
    published: int
    failed: int


class PostsPageResponse(BaseModel):
    data: list[PostListItemResponse]
    # Every status's, whichever one the page lists, for the tabs and the sidebar's badge.
    counts: PostCountsResponse
    # The offset of the next page, or None on the last one.
    next_offset: Optional[int]


class ScheduledPostToolResponse(ScheduledPostResponse):
    """A Scheduled post as an MCP tool answers with it, linking to its Post in the web app."""

    post_url: str


class PostNowToolResponse(ScheduledPostToolResponse):
    """`message` says how Post now ended, as the web app tells the User after Post now."""

    message: str


class PostMessageToolResponse(BaseModel):
    message: str
    post_url: str


class ScheduledPostUpdateRequest(BaseModel):
    """Leave out what stays the same; `rules.ScheduledPostEdit` refuses an edit of nothing."""

    model_config = ConfigDict(extra="forbid")

    # Every Part in order, replacing those not live; live Parts come first, unchanged.
    parts: Optional[Parts] = None
    # Copy the Post's Text again: its Parts after the live ones replace those not live.
    copy_text: bool = False
    # A new time reschedules the Scheduled post on the X account connected now.
    publish_at: Optional[AwareDatetime] = None
    # Publishes it within the request, on the X account connected now.
    publish_now: bool = False
    # The ID or URL of a new Community; an explicit null moves it back to the User's profile.
    community: Optional[str] = Field(None, max_length=COMMUNITY_PASTE_MAX_CHARS)
    # Ignored when the Scheduled post ends up on the profile.
    share_with_followers: Optional[bool] = None

    _strip = field_validator("parts")(_strip_parts)


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: str = Field(..., max_length=FEEDBACK_MAX_CHARS)
    # None keeps the Text's Format.
    format: Optional[Format] = None
    # The Text's Parts as the sender shows them. When set, Feedback is refused unless they are the
    # saved Text, so it never rewrites a Text without the User's latest edit.
    text: Optional[Parts] = None

    @field_validator("feedback")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Write some Feedback first.")
        return stripped


class TextEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Every Part of the Text in order, as typed, so a Part may be blank while the User writes it.
    parts: Parts


class XConnectionResponse(BaseModel):
    """The User's X connection. Tokens never leave the backend."""

    handle: str
    # The longest Scheduled post X accepts from this account, in X's weighted characters.
    char_limit: int
    needs_reconnect: bool
    # Scheduled posts for this X account not yet published; disconnecting makes them fail.
    scheduled_posts_waiting: int
    # X's URL for the X account's photo; None when X gave none.
    photo_url: Optional[str]
