from datetime import datetime
from typing import Annotated, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from pumpkit.posts.formats import part_name
from pumpkit.posts.schemas import VersionResponse, VersionToolResponse
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

    # The Version whose text the server copies: a Scheduled post is never typed (ADR 0015).
    source_version_id: str
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
    # The Version whose text it copied; None only for one typed before ADR 0015.
    source_version_id: Optional[str]
    # The Community it goes to; None for the User's profile.
    community: Optional[CommunityResponse]
    share_with_followers: bool
    created_at: datetime


class PostDetailResponse(BaseModel):
    """One Post with its Versions in order, and the status its one Scheduled post gives it."""

    id: str
    brief: str
    versions: list[VersionResponse]
    status: PostStatus
    # None while the Post is a Draft.
    scheduled_post: Optional[ScheduledPostResponse]


class PostDetailToolResponse(BaseModel):
    """A Post as the `get_post` tool answers with it, without the tells."""

    id: str
    brief: str
    versions: list[VersionToolResponse]
    status: PostStatus
    scheduled_post: Optional[ScheduledPostResponse]


class ScheduledPostsListResponse(BaseModel):
    data: list[ScheduledPostResponse]


class ScheduledPostToolResponse(ScheduledPostResponse):
    """A Scheduled post as an MCP tool answers with it, linking to the web app's Posts page."""

    scheduled_page_url: str


class PostNowToolResponse(ScheduledPostToolResponse):
    """`message` says how Post now ended, as the web app tells the User after Post now."""

    message: str


class ScheduledPostsListToolResponse(ScheduledPostsListResponse):
    scheduled_page_url: str


class ScheduledPageMessageToolResponse(BaseModel):
    message: str
    scheduled_page_url: str


class ScheduledPostUpdateRequest(BaseModel):
    """Leave out what stays the same; `rules.ScheduledPostEdit` refuses an edit of nothing."""

    model_config = ConfigDict(extra="forbid")

    # Every Part in order, replacing those not live; live Parts come first, unchanged.
    parts: Optional[Parts] = None
    # A new time reschedules the Scheduled post on the X account connected now.
    publish_at: Optional[AwareDatetime] = None
    # The ID or URL of a new Community; an explicit null moves it back to the User's profile.
    community: Optional[str] = Field(None, max_length=COMMUNITY_PASTE_MAX_CHARS)
    # Ignored when the Scheduled post ends up on the profile.
    share_with_followers: Optional[bool] = None

    _strip = field_validator("parts")(_strip_parts)


class XConnectionResponse(BaseModel):
    """The User's X connection. Tokens never leave the backend."""

    handle: str
    # The longest Scheduled post X accepts from this account, in X's weighted characters.
    char_limit: int
    needs_reconnect: bool
    # Scheduled posts for this X account not yet published; disconnecting makes them fail.
    scheduled_posts_waiting: int
