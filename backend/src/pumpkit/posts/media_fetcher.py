"""
The `MediaUrlFetcher` port: downloading a Media file an AI app names by its public URL, through
the public-host guard in `core/public_http.py`. The file is sniffed and capped by its kind while it
downloads, as an upload is. Touches no database.

Mediators reach the network only through `get_media_url_fetcher`; tests override it with
`FakeMediaUrlFetcher`.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional, Protocol
from urllib.parse import urljoin

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

# Long enough for the largest image on a slow host.
_DEADLINE_SECONDS = 60.0
_MAX_REDIRECTS = 3


def media_url_unreachable(reason: str) -> MediaRefused:
    return MediaRefused(
        f"Pumpkit couldn't download media from this URL ({reason}). Give a public https URL that"
        " serves the media itself.",
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
    Downloads with no proxy or compression, 60 seconds in all, following up to 3 redirects, each
    to a destination the guard checks again.
    """

    resolve: Resolver = resolve_with_getaddrinfo
    network: httpcore.AsyncNetworkBackend = field(default_factory=anyio_network)
    deadline_seconds: float = _DEADLINE_SECONDS

    @asynccontextmanager
    async def fetch(self, url: str) -> AsyncIterator[ReceivedMedia]:
        incoming = IncomingMedia()
        try:
            try:
                async with asyncio.timeout(self.deadline_seconds):
                    await self._download(url, incoming)
            except TimeoutError:
                raise media_url_unreachable("took too long") from None
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
                raise media_url_unreachable(str(error)) from error
            if location is None:
                return
            url = location
        raise media_url_unreachable(f"redirects more than {_MAX_REDIRECTS} times")


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
            raise media_url_unreachable("answered HTTP 404")
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
