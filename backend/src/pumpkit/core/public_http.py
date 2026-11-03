"""
Requests to URLs that a caller names, such as an app's metadata document or an image an AI app
links to, guarded against reaching anything but the public internet (server-side request
forgery). Each request goes to an address the guard checked, never to one a second DNS lookup
returns, with no redirects, proxy or environment settings.
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Optional, TypeVar, cast
from urllib.parse import urlsplit

import httpcore
import httpx

from pumpkit.core.config import settings

# NAT64 prefixes embed an IPv4 address, which may be private, behind an address `is_global` passes.
_NAT64_NETWORKS = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))

Resolver = Callable[[str, int], Awaitable[list[str]]]
T = TypeVar("T")


class PublicFetchError(Exception):
    """The URL names a host Pumpkit may not reach, or the host couldn't be reached."""


async def resolve_with_getaddrinfo(host: str, port: int) -> list[str]:
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


def anyio_network() -> httpcore.AsyncNetworkBackend:
    # httpcore declares `AnyIOBackend` conditionally, so its base class is invisible to pyright.
    return cast(httpcore.AsyncNetworkBackend, httpcore.AnyIOBackend())


async def fetch_public(
    url: str,
    attempt: Callable[[httpx.AsyncClient], Awaitable[T]],
    *,
    resolve: Resolver,
    network: httpcore.AsyncNetworkBackend,
    timeout_seconds: float,
) -> T:
    """
    What `attempt` makes of a client connected to `url`'s host, tried on each address the host
    resolves to in order, once every one of them is allowed. The client follows no redirects.
    """
    addresses = await _check_destination(url, resolve)
    try:
        for address in addresses[:-1]:
            try:
                return await _attempt_on(address, attempt, network, timeout_seconds)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                continue
        return await _attempt_on(addresses[-1], attempt, network, timeout_seconds)
    # InvalidURL isn't an HTTPError: httpx raises it for a URL it refuses to send.
    except (httpx.HTTPError, httpx.InvalidURL) as error:
        raise PublicFetchError(f"unreachable: {type(error).__name__}") from error


def check_answer(response: httpx.Response) -> None:
    """Refuses an answer other than 200, and a compressed one."""
    if response.status_code != 200:
        raise PublicFetchError(f"answered HTTP {response.status_code}")
    # A compressed body would be expanded before a size cap could stop it.
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        raise PublicFetchError("answered a compressed body")


async def _attempt_on(
    address: str,
    attempt: Callable[[httpx.AsyncClient], Awaitable[T]],
    network: httpcore.AsyncNetworkBackend,
    timeout_seconds: float,
) -> T:
    transport = _PinnedTransport(_PinnedNetwork(address, network))
    async with httpx.AsyncClient(
        transport=transport, timeout=timeout_seconds, follow_redirects=False, trust_env=False
    ) as http:
        return await attempt(http)


async def _check_destination(url: str, resolve: Resolver) -> list[str]:
    """
    The addresses to try in order, once every address the host resolves to is global. Outside
    `ENV=local` the URL must be https, on port 443, naming a host rather than an IP address.
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        port = parts.port
    except ValueError:
        raise PublicFetchError("names a port that isn't a number from 0 to 65535") from None
    local = settings.ENV == "local"
    # The dev stack serves files from this computer over plain http.
    if parts.scheme != "https" and not (local and parts.scheme == "http"):
        raise PublicFetchError("isn't an https URL")
    if not local:
        if _is_ip_literal(host):
            raise PublicFetchError("names an IP address instead of a host")
        if port not in (None, 443):
            raise PublicFetchError("names a port other than 443")
    try:
        addresses = await resolve(host, port or (443 if parts.scheme == "https" else 80))
    # IDNA encoding raises UnicodeError for a label that is empty or over 63 characters.
    except (OSError, UnicodeError) as error:
        raise PublicFetchError(f"host unresolvable: {type(error).__name__}") from error
    if not addresses:
        raise PublicFetchError("host resolves to no address")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        # The dev stack and tests serve documents from this computer.
        if not (ip.is_global or (local and ip.is_loopback)) or any(
            ip in network for network in _NAT64_NETWORKS
        ):
            raise PublicFetchError("host resolves to a non-global address")
    return addresses


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
