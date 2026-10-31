"""
The `XReader` port: reads an X account's profile and an Inspiration author's recent posts from X
(ADR 0005), and a Community's name for a Scheduled post going there.

It returns plain data and never touches the database: storing posts is the callers' job.
A handle X doesn't know is a `HandleNotFoundError` (a `HandleSuspendedError` when X suspended
it), and a Community a `CommunityNotFoundError`;
any other provider failure is an `XReaderError` (a 502 with an `error_id`), and a missing API
key an `XReaderNotConfiguredError`.

Mediators reach X only through `get_x_reader`; tests override it with `FakeXReader`.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable, Optional, Protocol

import httpx

from pumpkit.core.config import settings
from pumpkit.core.errors import AppError, NotConfiguredError

TWITTERAPI_IO_LAST_TWEETS_URL = "https://api.twitterapi.io/twitter/user/last_tweets"
TWITTERAPI_IO_USER_INFO_URL = "https://api.twitterapi.io/twitter/user/info"
# twitterapi.io docs say this is slow.
TWITTERAPI_IO_COMMUNITY_INFO_URL = "https://api.twitterapi.io/twitter/community/info"
_TIMEOUT_SECONDS = 30.0

# X's own timestamp format, e.g. "Wed Jul 22 17:44:05 +0000 2026".
_CREATED_AT_FORMAT = "%a %b %d %H:%M:%S %z %Y"

# twitterapi.io doesn't document unknown handles, so a 404 or a matching error message is one.
# An empty timeline reads as "no original posts" instead.
_NOT_FOUND_MESSAGE = re.compile(r"not found|not exist|no such user", re.IGNORECASE)


class XReaderError(AppError):
    """Reading from X failed: network, HTTP, or a response that can't be read."""

    status_code = 502
    public_detail = "X can't be read right now. Please try again later."
    reported = True


class XReaderNotConfiguredError(NotConfiguredError, XReaderError):
    """Raised when X is read without TWITTERAPI_IO_API_KEY configured."""

    def __init__(self) -> None:
        super().__init__("TWITTERAPI_IO_API_KEY is not set. Add it to .env to read X posts.")


class HandleNotFoundError(XReaderError):
    """X has no account under this handle."""


class HandleSuspendedError(HandleNotFoundError):
    """X suspended the account under this handle."""


class CommunityNotFoundError(XReaderError):
    """X has no Community with this ID."""


@dataclass(frozen=True)
class FetchedPost:
    """One original post or quote, as X returned it."""

    post_id: str
    text: str
    posted_at: datetime


@dataclass(frozen=True)
class FetchedProfile:
    """
    An X account as its profile shows it. The photo is X's small (48px) variant; a protected
    account's posts can't be read.
    """

    handle: str
    name: Optional[str]
    photo_url: Optional[str]
    protected: bool


@dataclass(frozen=True)
class RecentPosts:
    """
    One page of a handle's kept posts, and the author's name and photo as the page shows them:
    the photo is X's small (48px) variant. Each is None when no post carried one.
    """

    posts: list[FetchedPost]
    photo_url: Optional[str] = None
    name: Optional[str] = None


@dataclass(frozen=True)
class FetchedCommunity:
    id: str
    name: str


class XReader(Protocol):
    async def look_up_profile(self, handle: str) -> FetchedProfile:
        """
        The handle's profile. Raises `HandleSuspendedError` for a suspended account,
        `HandleNotFoundError` for an unknown handle, else `XReaderError`.
        """
        ...

    async def fetch_recent_posts(self, handle: str) -> RecentPosts:
        """
        One page (about 20) of the handle's newest posts, keeping only original posts and
        quotes. Raises `HandleNotFoundError` for an unknown handle, else `XReaderError`.
        """
        ...

    async def fetch_community(self, community_id: str) -> FetchedCommunity:
        """Raises `CommunityNotFoundError` for an unknown Community, else `XReaderError`."""
        ...


class TwitterApiIoReader:
    """Reads X through twitterapi.io. The key is checked on use, so the app boots without it."""

    async def look_up_profile(self, handle: str) -> FetchedProfile:
        response = await _get(TWITTERAPI_IO_USER_INFO_URL, {"userName": handle})
        return parse_user_info(response.status_code, _json_or_none(response))

    async def fetch_recent_posts(self, handle: str) -> RecentPosts:
        response = await _get(
            TWITTERAPI_IO_LAST_TWEETS_URL, {"userName": handle, "includeReplies": "false"}
        )
        return parse_last_tweets(response.status_code, _json_or_none(response))

    async def fetch_community(self, community_id: str) -> FetchedCommunity:
        response = await _get(TWITTERAPI_IO_COMMUNITY_INFO_URL, {"community_id": community_id})
        return parse_community_info(response.status_code, _json_or_none(response))


async def _get(url: str, params: dict[str, str]) -> httpx.Response:
    if not settings.TWITTERAPI_IO_API_KEY:
        raise XReaderNotConfiguredError()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            return await client.get(
                url, headers={"x-api-key": settings.TWITTERAPI_IO_API_KEY}, params=params
            )
    except httpx.HTTPError as error:
        raise XReaderError(f"twitterapi.io unreachable: {type(error).__name__}") from error


def _json_or_none(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def parse_last_tweets(status_code: int, payload: Any) -> RecentPosts:
    """The kept posts out of one `last_tweets` answer, or the error it stands for."""
    message = _error_message(payload)
    if status_code == 404 or (message is not None and _NOT_FOUND_MESSAGE.search(message)):
        raise HandleNotFoundError("twitterapi.io has no such user")
    # Only the status goes into the error: the body may echo request details.
    if status_code != 200:
        raise XReaderError(f"twitterapi.io returned HTTP {status_code}")
    if not isinstance(payload, dict):
        raise XReaderError("twitterapi.io returned a body that is not a JSON object")
    if message is not None:
        raise XReaderError("twitterapi.io returned an error status")

    tweets = _page_tweets(payload)
    posts = []
    for tweet in tweets:
        post = _kept_post(tweet)
        if post is not None:
            posts.append(post)
    return RecentPosts(posts=posts, photo_url=_author_photo_url(tweets), name=_author_name(tweets))


def parse_user_info(status_code: int, payload: Any) -> FetchedProfile:
    """The profile out of one `user/info` answer, or the error it stands for."""
    message = _error_message(payload)
    if status_code == 404 or (message is not None and _NOT_FOUND_MESSAGE.search(message)):
        raise HandleNotFoundError("twitterapi.io has no such user")
    if status_code != 200:
        raise XReaderError(f"twitterapi.io returned HTTP {status_code}")
    if not isinstance(payload, dict):
        raise XReaderError("twitterapi.io returned a body that is not a JSON object")
    if message is not None:
        raise XReaderError("twitterapi.io returned an error status")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise XReaderError("twitterapi.io answered without a profile")
    # A suspended account answers success, with only these flags in place of the profile.
    if data.get("unavailable"):
        if str(data.get("unavailableReason", "")).lower() == "suspended":
            raise HandleSuspendedError("twitterapi.io says the user is suspended")
        raise HandleNotFoundError("twitterapi.io says the user is unavailable")
    handle = data.get("userName")
    if not isinstance(handle, str) or not handle:
        raise XReaderError("twitterapi.io returned a profile without a handle")
    return FetchedProfile(
        handle=handle,
        name=_text_or_none(data.get("name")),
        photo_url=_https_or_none(data.get("profilePicture")),
        protected=data.get("protected") is True,
    )


def parse_community_info(status_code: int, payload: Any) -> FetchedCommunity:
    """The Community out of one `community/info` answer, or the error it stands for."""
    message = _error_message(payload)
    # Its documented error body is `{"error": <code>, "message": ...}`, without a status.
    if message is None and isinstance(payload, dict) and isinstance(payload.get("error"), int):
        message = payload.get("message") if isinstance(payload.get("message"), str) else ""
    if status_code == 404 or (message is not None and _NOT_FOUND_MESSAGE.search(message)):
        raise CommunityNotFoundError("twitterapi.io has no such Community")
    if status_code != 200:
        raise XReaderError(f"twitterapi.io returned HTTP {status_code}")
    if not isinstance(payload, dict):
        raise XReaderError("twitterapi.io returned a body that is not a JSON object")
    if message is not None:
        raise XReaderError("twitterapi.io returned an error status")

    # A success without the Community in it is how an unknown ID can come back.
    info = payload.get("community_info")
    if not isinstance(info, dict) or info.get("id") is None:
        raise CommunityNotFoundError("twitterapi.io answered without a Community")
    name = info.get("name")
    if not isinstance(name, str) or not name.strip():
        raise XReaderError("twitterapi.io returned a Community without a name")
    return FetchedCommunity(id=str(info["id"]), name=name.strip())


def _error_message(payload: Any) -> Optional[str]:
    """The message of an error body (`status: "error"`), or None when it isn't one."""
    if not isinstance(payload, dict) or payload.get("status") != "error":
        return None
    message = payload.get("message") or payload.get("msg") or ""
    return message if isinstance(message, str) else ""


def _page_tweets(payload: dict) -> list:
    # The endpoint has been seen answering both shapes; reading one turns the other into
    # a silently empty timeline.
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("tweets"), list):
        return data["tweets"]
    tweets = payload.get("tweets")
    return tweets if isinstance(tweets, list) else []


def _author_photo_url(tweets: list) -> Optional[str]:
    """
    The first https `author.profilePicture` on the page. Every post on a user's timeline,
    their reposts too, has them as its author.
    """
    return _first_author_field(tweets, "profilePicture", _https_or_none)


def _author_name(tweets: list) -> Optional[str]:
    return _first_author_field(tweets, "name", _text_or_none)


def _first_author_field(
    tweets: list, key: str, read: Callable[[Any], Optional[str]]
) -> Optional[str]:
    for tweet in tweets:
        author = tweet.get("author") if isinstance(tweet, dict) else None
        value = read(author.get(key)) if isinstance(author, dict) else None
        if value is not None:
            return value
    return None


def _https_or_none(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value.startswith("https://") else None


def _text_or_none(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _kept_post(tweet: Any) -> Optional[FetchedPost]:
    """
    The post if it is worth learning from: replies (thread continuations too) and bare
    reposts are dropped, quotes kept. So is anything without an id, text or readable date.
    """
    if not isinstance(tweet, dict):
        return None
    if tweet.get("retweeted_tweet") or tweet.get("isReply"):
        return None
    post_id = tweet.get("id")
    text = tweet.get("text")
    text = text.strip() if isinstance(text, str) else ""
    try:
        posted_at = datetime.strptime(tweet.get("createdAt") or "", _CREATED_AT_FORMAT)
    except (TypeError, ValueError):
        return None
    if post_id is None or not text:
        return None
    return FetchedPost(post_id=str(post_id), text=text, posted_at=posted_at)


@dataclass
class FakeXReader:
    """
    X in memory: answers a handle's posts with `posts[handle]`, `photos.get(handle)` and
    `names.get(handle)`; its profile with `profiles[handle]`, a suspension for a handle in
    `suspended`, or a public profile for a handle with `posts`; and a Community ID with `communities[id]` (its name). Anything else is a
    not-found error. Records each handle read in `calls`, each profile looked up in
    `profile_calls` and each Community ID in `community_calls`. Set `fail` or `not_configured`
    to raise.
    """

    posts: dict[str, list[FetchedPost]] = field(default_factory=dict)
    photos: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    profiles: dict[str, FetchedProfile] = field(default_factory=dict)
    suspended: set[str] = field(default_factory=set)
    communities: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    profile_calls: list[str] = field(default_factory=list)
    community_calls: list[str] = field(default_factory=list)
    fail: bool = False
    not_configured: bool = False

    async def look_up_profile(self, handle: str) -> FetchedProfile:
        self.profile_calls.append(handle)
        if self.not_configured:
            raise XReaderNotConfiguredError()
        if self.fail:
            raise XReaderError("Fake X reader is set to fail")
        if handle in self.suspended:
            raise HandleSuspendedError(f"Fake X reader has {handle} suspended")
        if handle in self.profiles:
            return self.profiles[handle]
        if handle in self.posts:
            return FetchedProfile(
                handle=handle,
                name=self.names.get(handle),
                photo_url=self.photos.get(handle),
                protected=False,
            )
        raise HandleNotFoundError(f"Fake X reader has no {handle}")

    async def fetch_recent_posts(self, handle: str) -> RecentPosts:
        self.calls.append(handle)
        if self.not_configured:
            raise XReaderNotConfiguredError()
        if self.fail:
            raise XReaderError("Fake X reader is set to fail")
        if handle not in self.posts:
            raise HandleNotFoundError(f"Fake X reader has no {handle}")
        return RecentPosts(
            posts=list(self.posts[handle]),
            photo_url=self.photos.get(handle),
            name=self.names.get(handle),
        )

    async def fetch_community(self, community_id: str) -> FetchedCommunity:
        self.community_calls.append(community_id)
        if self.not_configured:
            raise XReaderNotConfiguredError()
        if self.fail:
            raise XReaderError("Fake X reader is set to fail")
        if community_id not in self.communities:
            raise CommunityNotFoundError(f"Fake X reader has no Community {community_id}")
        return FetchedCommunity(id=community_id, name=self.communities[community_id])


@lru_cache
def get_x_reader() -> XReader:
    """FastAPI dependency for the `XReader` port."""
    return TwitterApiIoReader()
