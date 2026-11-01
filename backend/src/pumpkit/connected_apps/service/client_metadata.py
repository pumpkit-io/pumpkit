"""
The `ClientMetadataFetcher` port, and apps that identify themselves by a Client ID Metadata
Document (CIMD): a `client_id` that is the https URL of a JSON document describing the app.

The fetcher only downloads: `resolve_metadata_document_client` validates the document and
caches it as the app's `OAuthClient` row, keyed by the URL. Flushes, never commits.

Mediators reach the network only through `get_client_metadata_fetcher`; tests override it with
`FakeClientMetadataFetcher`.
"""

import asyncio
import ipaddress
import json
import re
import socket
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional, Protocol, cast
from urllib.parse import urlsplit

import httpcore
import httpx
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.connected_apps.models import OAuthClient
from pumpkit.connected_apps.schemas import ClientMetadataDocument
from pumpkit.core.config import settings
from pumpkit.core.logging import logger
from pumpkit.core.time import as_utc

_TIMEOUT_SECONDS = 5.0
_MAX_DOCUMENT_BYTES = 8 * 1024
_MIN_FRESHNESS = timedelta(minutes=5)
_MAX_FRESHNESS = timedelta(hours=24)
# NAT64 prefixes embed an IPv4 address, which may be private, behind an address `is_global` passes.
_NAT64_NETWORKS = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))
_MAX_AGE = re.compile(r"(?:^|,)\s*max-age\s*=\s*(\d+)\s*(?:,|$)", re.IGNORECASE)
_KNOWN_DOCUMENTS_PATH = Path(__file__).with_name("known_client_documents.json")

Resolver = Callable[[str, int], Awaitable[list[str]]]


class ClientMetadataFetchError(Exception):
    """The document couldn't be fetched, or what came back isn't a JSON document."""


@dataclass(frozen=True)
class FetchedClientMetadata:
    """A document as fetched, and the `max-age` its answer allowed caching it for."""

    document: Any
    max_age_seconds: Optional[int] = None


class ClientMetadataFetcher(Protocol):
    async def fetch(self, url: str) -> FetchedClientMetadata:
        """The JSON at `url`, or `ClientMetadataFetchError`."""
        ...


def is_metadata_document_url(client_id: str) -> bool:
    """Whether a `client_id` names a metadata document: an https URL with a non-root path."""
    try:
        parts = urlsplit(client_id)
        has_valid_port = parts.port != 0
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and has_valid_port
        and parts.path not in ("", "/")
        and "#" not in client_id
        and "@" not in parts.netloc
    )


async def _resolve_with_getaddrinfo(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    return [str(info[4][0]) for info in infos]


@dataclass(frozen=True)
class _PinnedNetwork(httpcore.AsyncNetworkBackend):
    """
    Connects to `address` whatever host the URL names, so a host can't answer the destination
    check with one address and the connection with another. TLS still verifies the URL's host.
    """

    address: str
    inner: httpcore.AsyncNetworkBackend

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options: Optional[Iterable[Any]] = None,
    ) -> httpcore.AsyncNetworkStream:
        return await self.inner.connect_tcp(
            self.address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: Optional[float] = None,
        socket_options: Optional[Iterable[Any]] = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("unix sockets are never used")

    async def sleep(self, seconds: float) -> None:
        await self.inner.sleep(seconds)


class _PinnedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, network: httpcore.AsyncNetworkBackend) -> None:
        super().__init__(trust_env=False)
        # httpx takes no network backend, so its pool is rebuilt with one.
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False), network_backend=network
        )


def _anyio_network() -> httpcore.AsyncNetworkBackend:
    # httpcore declares `AnyIOBackend` conditionally, so its base class is invisible to pyright.
    return cast(httpcore.AsyncNetworkBackend, httpcore.AnyIOBackend())


@dataclass(frozen=True)
class HttpClientMetadataFetcher:
    """
    Fetches over https with no redirects or proxy, 5 seconds in all and 8 KB at most, connecting
    to the address it checked. Outside `ENV=local` it refuses IP-literal hosts, ports other than
    443 and any host resolving to a non-global address.
    """

    resolve: Resolver = _resolve_with_getaddrinfo
    network: httpcore.AsyncNetworkBackend = field(default_factory=_anyio_network)
    deadline_seconds: float = _TIMEOUT_SECONDS

    async def fetch(self, url: str) -> FetchedClientMetadata:
        try:
            async with asyncio.timeout(self.deadline_seconds):
                body, cache_control = await self._download(url)
        except TimeoutError:
            raise ClientMetadataFetchError("took too long") from None
        try:
            document = json.loads(body)
        # Deeply nested arrays under the size cap exhaust the parser's recursion.
        except (ValueError, RecursionError):
            raise ClientMetadataFetchError("answered something other than JSON") from None
        return FetchedClientMetadata(document, _max_age(cache_control))

    async def _download(self, url: str) -> tuple[bytes, str]:
        address = await self._check_destination(url)
        transport = _PinnedTransport(_PinnedNetwork(address, self.network))
        try:
            async with httpx.AsyncClient(
                transport=transport,
                timeout=self.deadline_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as http:
                async with http.stream(
                    "GET",
                    url,
                    headers={"Accept": "application/json", "Accept-Encoding": "identity"},
                ) as response:
                    if response.status_code != 200:
                        raise ClientMetadataFetchError(f"answered HTTP {response.status_code}")
                    body = await _read_capped(response)
                    return body, response.headers.get("cache-control", "")
        except httpx.HTTPError as error:
            raise ClientMetadataFetchError(f"unreachable: {type(error).__name__}") from error

    async def _check_destination(self, url: str) -> str:
        """The address to connect to, once every address the host resolves to is allowed."""
        parts = urlsplit(url)
        host = parts.hostname or ""
        local = settings.ENV == "local"
        if not local:
            if _is_ip_literal(host):
                raise ClientMetadataFetchError("names an IP address instead of a host")
            if parts.port not in (None, 443):
                raise ClientMetadataFetchError("names a port other than 443")
        try:
            addresses = await self.resolve(host, parts.port or 443)
        # IDNA encoding raises UnicodeError for a label that is empty or over 63 characters.
        except (OSError, UnicodeError) as error:
            raise ClientMetadataFetchError(f"host unresolvable: {type(error).__name__}") from error
        if not addresses:
            raise ClientMetadataFetchError("host resolves to no address")
        for address in addresses:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
            # The dev stack and tests serve documents from this computer.
            if not (ip.is_global or (local and ip.is_loopback)) or any(
                ip in network for network in _NAT64_NETWORKS
            ):
                raise ClientMetadataFetchError("host resolves to a non-global address")
        return addresses[0]


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


async def _read_capped(response: httpx.Response) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > _MAX_DOCUMENT_BYTES:
            raise ClientMetadataFetchError(f"is larger than {_MAX_DOCUMENT_BYTES} bytes")
    return bytes(body)


def _max_age(cache_control: str) -> Optional[int]:
    match = _MAX_AGE.search(cache_control)
    if match is None:
        return None
    try:
        return int(match.group(1))
    # Past Python's 4300-digit limit for int().
    except ValueError:
        return None


@dataclass
class FakeClientMetadataFetcher:
    """
    Answers each URL with its entry in `documents`, which `serve` fills by the document's own
    `client_id`; any other URL fails, as an unreachable host would. Records each URL in `fetched`.
    """

    documents: dict[str, FetchedClientMetadata] = field(default_factory=dict)
    fetched: list[str] = field(default_factory=list)

    def serve(self, document: dict, *, max_age_seconds: Optional[int] = None) -> None:
        self.documents[document["client_id"]] = FetchedClientMetadata(document, max_age_seconds)

    async def fetch(self, url: str) -> FetchedClientMetadata:
        self.fetched.append(url)
        if url not in self.documents:
            raise ClientMetadataFetchError("Fake fetcher has no document there")
        return self.documents[url]


@lru_cache
def get_client_metadata_fetcher() -> ClientMetadataFetcher:
    """FastAPI dependency for the `ClientMetadataFetcher` port."""
    return HttpClientMetadataFetcher()


@lru_cache
def _known_documents() -> dict[str, Any]:
    return json.loads(_KNOWN_DOCUMENTS_PATH.read_text())


async def resolve_metadata_document_client(
    db: AsyncSession, url: str, fetcher: ClientMetadataFetcher, *, now: datetime
) -> Optional[OAuthClient]:
    """
    The app the document at `url` describes, or None when it can't be had or is invalid. A fresh
    cached copy is used as is. When fetching fails, a cached copy is used however stale, then a
    copy bundled for the big clients, whose bot protection sometimes refuses servers.
    """
    cached = await db.get(OAuthClient, url)
    if cached is not None and cached.kind != "metadata_document":
        return None
    if cached is not None and _is_fresh(cached, now):
        return cached

    try:
        fetched = await fetcher.fetch(url)
    except ClientMetadataFetchError as error:
        host = urlsplit(url).hostname
        if cached is not None:
            logger.warning("Metadata document at %s %s; using the cached copy", host, error)
            return cached
        known = _known_documents().get(url)
        if known is None:
            logger.warning("Metadata document at %s %s", host, error)
            return None
        logger.warning("Metadata document at %s %s; using the bundled copy", host, error)
        fetched_at = datetime.fromisoformat(known["fetched_at"])
        # Stale at once, so the next authorization tries the live document again.
        return await _store(
            db, url, known["document"], cached, now=now, fetched_at=fetched_at, expires_at=now
        )

    expires_at = now + _freshness(fetched.max_age_seconds)
    return await _store(
        db, url, fetched.document, cached, now=now, fetched_at=now, expires_at=expires_at
    )


def _is_fresh(client: OAuthClient, now: datetime) -> bool:
    expires_at = client.metadata_expires_at
    return expires_at is not None and as_utc(expires_at) > now


def _freshness(max_age_seconds: Optional[int]) -> timedelta:
    if max_age_seconds is None:
        return _MAX_FRESHNESS
    seconds = min(max_age_seconds, int(_MAX_FRESHNESS.total_seconds()))
    return max(timedelta(seconds=seconds), _MIN_FRESHNESS)


async def _store(
    db: AsyncSession,
    url: str,
    raw: Any,
    cached: Optional[OAuthClient],
    *,
    now: datetime,
    fetched_at: datetime,
    expires_at: datetime,
) -> Optional[OAuthClient]:
    document = _validated(url, raw)
    if document is None:
        return None
    client = cached or OAuthClient(id=url, kind="metadata_document", created_at=now)
    client.name = document.client_name or str(urlsplit(url).hostname)
    client.redirect_uris = document.redirect_uris
    # Every metadata document app is public: PKCE binds its code, and no secret is ever issued.
    client.token_endpoint_auth_method = "none"
    client.client_secret_hash = None
    client.client_uri = document.client_uri
    client.logo_uri = document.logo_uri
    client.software_id = document.software_id
    client.software_version = document.software_version
    client.metadata_fetched_at = fetched_at
    client.metadata_expires_at = expires_at
    if cached is not None:
        await db.flush()
        return client
    try:
        # A savepoint, so losing the race to another first authorization keeps the transaction.
        async with db.begin_nested():
            db.add(client)
    except IntegrityError:
        winner = await db.get(OAuthClient, url)
        if winner is None:
            raise
        return winner
    return client


def _validated(url: str, raw: Any) -> Optional[ClientMetadataDocument]:
    host = urlsplit(url).hostname
    if not isinstance(raw, dict):
        logger.warning("Metadata document at %s is not a JSON object", host)
        return None
    try:
        document = ClientMetadataDocument.model_validate(raw)
    except ValidationError as error:
        first = error.errors()[0]
        field_name = ".".join(str(part) for part in first["loc"])
        logger.warning("Metadata document at %s refused: %s is invalid", host, field_name)
        return None
    if document.client_id != url:
        logger.warning("Metadata document at %s names another client_id", host)
        return None
    return document
