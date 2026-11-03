"""
The `MediaUrlFetcher` port: downloading a Media file an AI app names by its public URL, through
the public-host guard in `core/public_http.py`. The file is sniffed and capped by its kind while it
downloads, as an upload is. Touches no database.

Mediators reach the network only through `get_media_url_fetcher`; tests override it with
`FakeMediaUrlFetcher`.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional, Protocol
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

from pumpkit.core.public_http import (
    PublicFetchError,
    Resolver,
    anyio_network,
    check_answer,
    fetch_public,
    resolve_with_getaddrinfo,
)
from pumpkit.posts.media_files import MediaRefused
from pumpkit.posts.media_upload import IncomingMedia, ReceivedMedia
from pumpkit.posts.models import MEDIA_GIF, MEDIA_VIDEO, MediaKind

# Long enough for the largest image on a slow host.
_DEADLINE_SECONDS = 60.0
# A larger kind's whole download, counted from its start once the file's first bytes name it.
# A minute under the web proxy's 5 minutes for an API answer, so the tool call gets its answer.
_LONGER_DEADLINES: Mapping[MediaKind, float] = {MEDIA_GIF: 2 * 60.0, MEDIA_VIDEO: 4 * 60.0}
_MAX_REDIRECTS = 3

logger = logging.getLogger(__name__)


def media_url_unreachable(url: str, reason: str) -> MediaRefused:
    """
    One answer for every reason, logged here instead: telling them apart would let a caller probe
    which internal hosts resolve or answer.
    """
    logger.info("Media download from %s refused: %s", urlsplit(url).hostname, reason)
    return MediaRefused(
        "Pumpkit couldn't download media from this URL. Give a public https URL that serves the"
        " media itself.",
        code="MEDIA_URL_UNREACHABLE",
    )


class MediaUrlFetcher(Protocol):
    def fetch(self, url: str) -> AbstractAsyncContextManager[ReceivedMedia]:
        """
        The file at `url`, spooled and rewound, until the context ends. Raises `MediaRefused`:
        unreachable, too large for its kind, or of a type Pumpkit doesn't take.
        """
        ...


@asynccontextmanager
async def _received(incoming: IncomingMedia) -> AsyncIterator[ReceivedMedia]:
    try:
        await incoming.upload.seek(0)
        yield ReceivedMedia(file=incoming.upload.file, byte_size=incoming.size)
    finally:
        await incoming.upload.close()


@dataclass(frozen=True)
class HttpMediaUrlFetcher:
    """
    Downloads with no proxy or compression, within one deadline, following a few redirects, each
    to a destination the guard checks again.
    """

    resolve: Resolver = resolve_with_getaddrinfo
    network: httpcore.AsyncNetworkBackend = field(default_factory=anyio_network)
    deadline_seconds: float = _DEADLINE_SECONDS
    longer_deadlines: Mapping[MediaKind, float] = field(default_factory=lambda: _LONGER_DEADLINES)

    @asynccontextmanager
    async def fetch(self, url: str) -> AsyncIterator[ReceivedMedia]:
        incoming = IncomingMedia()
        started = asyncio.get_running_loop().time()
        try:
            try:
                async with asyncio.timeout(self.deadline_seconds) as deadline:

                    def extend(kind: MediaKind) -> None:
                        if kind in self.longer_deadlines:
                            deadline.reschedule(started + self.longer_deadlines[kind])

                    incoming.on_kind = extend
                    await self._download(url, incoming)
            except TimeoutError:
                raise media_url_unreachable(url, "took too long") from None
        except BaseException:
            await incoming.upload.close()
            raise
        async with _received(incoming) as received:
            yield received

    async def _download(self, url: str, incoming: IncomingMedia) -> None:
        for _ in range(_MAX_REDIRECTS + 1):

            async def attempt(http: httpx.AsyncClient, url: str = url) -> Optional[str]:
                return await _get(http, url, incoming)

            try:
                location = await fetch_public(
                    url,
                    attempt,
                    resolve=self.resolve,
                    network=self.network,
                    timeout_seconds=self.deadline_seconds,
                )
            except PublicFetchError as error:
                raise media_url_unreachable(url, str(error)) from error
            if location is None:
                return
            url = location
        raise media_url_unreachable(url, f"redirects more than {_MAX_REDIRECTS} times")


async def _get(http: httpx.AsyncClient, url: str, incoming: IncomingMedia) -> Optional[str]:
    """Takes the file at `url` into `incoming`, or answers the URL it redirects to."""
    async with http.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
        if response.is_redirect and "location" in response.headers:
            return urljoin(url, response.headers["location"])
        check_answer(response)
        async for chunk in response.aiter_raw():
            await incoming.take(chunk)
        incoming.end()
        return None


@dataclass
class FakeMediaUrlFetcher:
    """
    Answers each URL with its file in `files`, which `serve` fills, checked as a download is; any
    other URL is unreachable. Records each URL in `fetched`.
    """

    files: dict[str, bytes] = field(default_factory=dict)
    fetched: list[str] = field(default_factory=list)

    def serve(self, url: str, data: bytes) -> None:
        self.files[url] = data

    @asynccontextmanager
    async def fetch(self, url: str) -> AsyncIterator[ReceivedMedia]:
        self.fetched.append(url)
        if url not in self.files:
            raise media_url_unreachable(url, "answered HTTP 404")
        incoming = IncomingMedia()
        try:
            await incoming.take(self.files[url])
            incoming.end()
        except BaseException:
            await incoming.upload.close()
            raise
        async with _received(incoming) as received:
            yield received


@lru_cache
def get_media_url_fetcher() -> MediaUrlFetcher:
    """FastAPI dependency for the `MediaUrlFetcher` port."""
    return HttpMediaUrlFetcher()
