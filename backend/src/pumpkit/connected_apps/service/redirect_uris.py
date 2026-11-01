"""Which redirect URIs an app may register, and when a requested one matches (RFC 8252)."""

import re
from urllib.parse import urlsplit

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_REFUSED_SCHEMES = frozenset(
    {"javascript", "data", "file", "vbscript", "about", "blob", "ws", "wss", "ftp"}
)
_PRIVATE_USE_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*$")
_CONTROL_OR_SPACE = re.compile(r"[\x00-\x20\x7f]")


class RedirectUriRefused(ValueError):
    """A redirect URI no app may register."""


def validate_redirect_uri(uri: str) -> str:
    """Return the URI when it may be registered, or raise `RedirectUriRefused`."""
    # A control character would let a registered URI split the Location header it ends up in.
    if _CONTROL_OR_SPACE.search(uri):
        raise RedirectUriRefused("Redirect URIs cannot contain spaces or control characters.")
    if "#" in uri:
        raise RedirectUriRefused("Redirect URIs cannot contain a fragment.")
    try:
        parts = urlsplit(uri)
        host = parts.hostname
    except ValueError:
        raise RedirectUriRefused("Redirect URI is not a valid URL.") from None

    scheme = parts.scheme
    if scheme in _REFUSED_SCHEMES:
        raise RedirectUriRefused(f"The {scheme} scheme cannot be a redirect URI.")
    if scheme == "https":
        if not host:
            raise RedirectUriRefused("An https redirect URI needs a host.")
    elif scheme == "http":
        if host not in _LOOPBACK_HOSTS:
            raise RedirectUriRefused("An http redirect URI must point to localhost.")
    elif not _PRIVATE_USE_SCHEME.match(scheme):
        raise RedirectUriRefused("Redirect URI needs an https, loopback http or app scheme.")
    return uri


def matches_registered(requested: str, registered: list[str]) -> bool:
    """
    Exact match, except a loopback http URI also matches one that differs only by port:
    CLIs listen on a free port per run, and a registered URI may name no port at all.
    """
    if requested in registered:
        return True
    key = _loopback_key(requested)
    return key is not None and any(_loopback_key(uri) == key for uri in registered)


def _loopback_key(uri: str) -> tuple[str, str, str] | None:
    parts = urlsplit(uri)
    if parts.scheme != "http" or parts.hostname not in _LOOPBACK_HOSTS:
        return None
    return parts.hostname, parts.path, parts.query
