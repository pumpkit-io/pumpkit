from datetime import datetime
from typing import Annotated, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from pumpkit.billing.allowance import WayOut
from pumpkit.posts.formats import Format
from pumpkit.posts.media_files import cleaned_alt_text
from pumpkit.posts.schemas import (
    FailedFeedbackResponse,
    MediaResponse,
    PlaceInBriefResponse,
    PlanResponse,
    TextResponse,
    VersionResponse,
)
from pumpkit.posts.writing.constants import FEEDBACK_MAX_CHARS
from pumpkit.posts.writing_state import WritingState
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
    """Trims each Part; the mediator refuses a blank one, as only it knows a first reply."""
    return None if value is None else [part.strip() for part in value]


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
    # Published with this Part, in order; a live Part's keeps only its preview.
    media: list[MediaResponse]


class ScheduledPostResponse(BaseModel):
    id: str
    # In the order they go out; one Part, or one and its first reply, is a single X post.
    parts: list[ScheduledPostPartResponse]
    # Whether the last Part is the single post's first reply, posted as a reply to it.
    first_reply: bool
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
    # Being published, or due and waiting for the publisher.
    posting: bool


class PostDetailResponse(BaseModel):
    """One Post with its Text, its Versions in order, and the status its Scheduled post gives it."""

    id: str
    brief: str
    brief_id: str
    place_in_brief: PlaceInBriefResponse
    # None for a Post written before Briefs were planned.
    plan: Optional[PlanResponse]
    # None until the Post's first Version is written.
    text: Optional[TextResponse]
    versions: list[VersionResponse]
    # "writing" while a Version is being written; "not_written" for a Post with no Text and no
    # write in progress, whose first Version failed or was lost and may be retried; else None.
    writing_state: Optional[WritingState]
    # The last Feedback when Pumpkit couldn't write its Version, until the User sends Feedback again,
    # changes the Text or dismisses it; None otherwise, and always while a Version is being written.
    failed_feedback: Optional[FailedFeedbackResponse]
    # None until the Post's first Version is written: a Post being written is not a Draft.
    status: Optional[PostStatus]
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
    # As on `ScheduledPostResponse`.
    posting: bool


class PostListItemResponse(BaseModel):
    id: str
    brief: str
    brief_id: str
    place_in_brief: PlaceInBriefResponse
    status: PostStatus
    # The Scheduled post's text when it has one, else the latest Version's; the first Part's
    # first line is the Post's title.
    parts: list[str]
    format: Format
    # Whether the last Part is the single post's first reply.
    first_reply: bool
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


URL_MAX_CHARS = 2048


class AttachMediaRequest(BaseModel):
    """What `attach_media` takes, checked before anything downloads."""

    part: int = Field(1, ge=1)
    url: Optional[str] = Field(None, max_length=URL_MAX_CHARS)
    alt_text: Optional[str] = None

    @field_validator("alt_text")
    @classmethod
    def _strip_and_limit(cls, value: Optional[str]) -> Optional[str]:
        return cleaned_alt_text(value)


class PlacedMediaResponse(BaseModel):
    media: MediaResponse
    # Whether the Post's waiting Scheduled post took it, rather than its Text.
    on_scheduled_post: bool


class AttachMediaToolResponse(BaseModel):
    message: str
    post_url: str
    # None when the app uploads the file through the link instead.
    media: Optional[MediaResponse]
    # A one-time link for the file, when no URL was given.
    upload_url: Optional[str] = None
    upload_expires_at: Optional[AwareDatetime] = None
    curl_command: Optional[str] = None


class UploadedMediaResponse(BaseModel):
    """What an upload through a one-time link answers, for the app that ran it."""

    message: str
    post_url: str
    media: MediaResponse


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
            raise ValueError("Write some feedback first.")
        return stripped


class TextEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Every Part of the Text in order, as typed, so a Part may be blank while the User writes it.
    parts: Parts
    # Whether the last Part is a single post's first reply; None keeps the Text's, and its Parts.
    first_reply: Optional[bool] = None


class XConnectionResponse(BaseModel):
    """The User's X connection. Tokens never leave the backend."""

    handle: str
    # The longest Scheduled post X accepts from this account, in X's weighted characters.
    char_limit: int
    # X Premium, which also lets the account post videos over 20 minutes.
    premium: bool
    needs_reconnect: bool
    # X's consent predates media.write, so attaching Media first takes reconnecting X.
    needs_reconnect_for_media: bool
    # Scheduled posts for this X account not yet published; disconnecting makes them fail.
    scheduled_posts_waiting: int
    # X's URL for the X account's photo; None when X gave none.
    photo_url: Optional[str]
    # Whether to ask the User, who has no Photo, to use the X account's photo as theirs.
    offer_photo: bool


class UsageCountResponse(BaseModel):
    """One count of an Allowance in the current period. A limit of None is no cap."""

    limit: Optional[int]
    used: int
    left: Optional[int]


class TopUpUsageResponse(BaseModel):
    """
    What one unexpired Top-up has left, spent only once the Allowance is used up; None for a count
    that had no cap when it was bought.
    """

    generations_left: Optional[int]
    x_posts_left: Optional[int]
    link_x_posts_left: Optional[int]
    expires_at: datetime


class AllowanceUsageResponse(BaseModel):
    """What the User has used and has left of the Allowance period holding now."""

    trial: bool
    # When the period ends: the next reset, or the Trial's end.
    resets_at: datetime
    # The day of the month each paid period resets on, also in months too short to have it;
    # None in a Trial.
    resets_on_day: Optional[int]
    generations: UsageCountResponse
    x_posts: UsageCountResponse
    # Of the X posts, those containing a link.
    link_x_posts: UsageCountResponse
    # What the User can do at a limit before the period resets; None when nothing.
    way_out: Optional[WayOut]
    # The User's Top-ups with something left, first to expire first.
    top_ups: list[TopUpUsageResponse]
    may_buy_top_up: bool


class UsageResponse(BaseModel):
    # None where the Instance sells no Plans or the User isn't Subscribed.
    allowance: Optional[AllowanceUsageResponse]
