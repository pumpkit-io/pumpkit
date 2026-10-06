"""
The `XReader` port: reads an Inspiration author's recent posts from X (ADR 0005).

It returns plain data and never touches the database: storing posts is the callers' job.
A handle X doesn't know is a `HandleNotFoundError`; any other provider failure is an
`XReaderError` (a 502 with an `error_id`), and a missing API key an `XReaderNotConfiguredError`.

Mediators reach X only through `get_x_reader`; tests override it with `FakeXReader`.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Optional, Protocol

import httpx

from app.core.config import settings

TWITTERAPI_IO_LAST_TWEETS_URL = "https://api.twitterapi.io/twitter/user/last_tweets"
_TIMEOUT_SECONDS = 30.0

# X's own timestamp format, e.g. "Wed Jul 22 17:44:05 +0000 2026".
_CREATED_AT_FORMAT = "%a %b %d %H:%M:%S %z %Y"

# twitterapi.io doesn't document its answer for an unknown handle: an HTTP 404, or an error
# body whose message says the user doesn't exist, counts as not found. An unknown handle
# answered with an empty timeline reads as "no original posts" instead.
_NOT_FOUND_MESSAGE = re.compile(r"not found|not exist|no such user", re.IGNORECASE)


class XReaderError(Exception):
    """Reading from X failed: network, HTTP, or a response that can't be read."""


class XReaderNotConfiguredError(XReaderError):
    """Raised when X is read without TWITTERAPI_IO_API_KEY configured."""

    def __init__(self) -> None:
        super().__init__(
            "TWITTERAPI_IO_API_KEY is not set. Add it to backend/.env to read X posts."
        )


class HandleNotFoundError(XReaderError):
    """X has no account under this handle."""


@dataclass(frozen=True)
class FetchedPost:
    """One original post or quote, as X returned it."""

    post_id: str
    text: str
    posted_at: datetime


class XReader(Protocol):
    async def fetch_recent_posts(self, handle: str) -> list[FetchedPost]:
        """
        One page (about 20) of the handle's newest posts, keeping only original posts and
        quotes. Raises `HandleNotFoundError` for an unknown handle, else `XReaderError`.
        """
        ...


class TwitterApiIoReader:
    """Reads X through twitterapi.io. The key is checked on use, so the app boots without it."""

    async def fetch_recent_posts(self, handle: str) -> list[FetchedPost]:
        if not settings.TWITTERAPI_IO_API_KEY:
            raise XReaderNotConfiguredError()
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    TWITTERAPI_IO_LAST_TWEETS_URL,
                    headers={"x-api-key": settings.TWITTERAPI_IO_API_KEY},
                    params={"userName": handle, "includeReplies": "false"},
                )
        except httpx.HTTPError as error:
            raise XReaderError(f"twitterapi.io unreachable: {type(error).__name__}") from error
        return parse_last_tweets(response.status_code, _json_or_none(response))


def _json_or_none(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def parse_last_tweets(status_code: int, payload: Any) -> list[FetchedPost]:
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

    posts = []
    for tweet in _page_tweets(payload):
        post = _kept_post(tweet)
        if post is not None:
            posts.append(post)
    return posts


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
    X in memory: answers a handle with `posts[handle]`, and an unknown handle with
    `HandleNotFoundError`. Records each handle read. Set `fail` or `not_configured` to raise.
    """

    posts: dict[str, list[FetchedPost]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    fail: bool = False
    not_configured: bool = False

    async def fetch_recent_posts(self, handle: str) -> list[FetchedPost]:
        self.calls.append(handle)
        if self.not_configured:
            raise XReaderNotConfiguredError()
        if self.fail:
            raise XReaderError("Fake X reader is set to fail")
        if handle not in self.posts:
            raise HandleNotFoundError(f"Fake X reader has no {handle}")
        return list(self.posts[handle])


@lru_cache
def get_x_reader() -> XReader:
    """FastAPI dependency for the `XReader` port."""
    return TwitterApiIoReader()
