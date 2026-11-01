import pytest

from pumpkit.connected_apps.service.redirect_uris import (
    RedirectUriRefused,
    matches_registered,
    validate_redirect_uri,
)


@pytest.mark.parametrize(
    "uri",
    [
        "https://claude.ai/api/mcp/auth_callback",
        "https://example.com/cb?tenant=1",
        "http://localhost:8080/callback",
        "http://localhost/callback",
        "http://127.0.0.1:33418/callback",
        "http://[::1]:9000/callback",
        "cursor://anysphere.cursor-retrieval/oauth/callback",
        "vscode://vscode.github-authentication/did-authenticate",
        "com.example.app:/oauth2redirect",
    ],
)
def test_allowed_redirect_uris_are_returned_unchanged(uri):
    assert validate_redirect_uri(uri) == uri


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.com/cb#fragment",
        "http://localhost/cb#fragment",
        "cursor://callback#fragment",
        "http://example.com/callback",
        "http://192.168.1.5/callback",
        "http://localhost.example.com/callback",
        "https:///callback",
        "http://",
        "javascript:alert(1)",
        "data:text/html,hi",
        "file:///etc/passwd",
        "vbscript:msgbox(1)",
        "about:blank",
        "blob:https://example.com/id",
        "wss://example.com/socket",
        "ws://localhost/socket",
        "ftp://example.com/file",
        "JavaScript:alert(1)",
        "/relative/path",
        "callback",
        "https://example.com/cb\r\nLocation: https://evil.test",
        "https://example.com/a b",
        "1app://callback",
        "",
    ],
)
def test_refused_redirect_uris(uri):
    with pytest.raises(RedirectUriRefused):
        validate_redirect_uri(uri)


@pytest.mark.parametrize(
    ("requested", "registered"),
    [
        ("https://claude.ai/api/mcp/auth_callback", ["https://claude.ai/api/mcp/auth_callback"]),
        ("cursor://a/b", ["https://example.com/cb", "cursor://a/b"]),
        ("http://127.0.0.1:51234/callback", ["http://127.0.0.1:33418/callback"]),
        ("http://localhost:51234/callback", ["http://localhost/callback"]),
        ("http://localhost/callback", ["http://localhost:8080/callback"]),
        ("http://[::1]:5000/cb?x=1", ["http://[::1]:6000/cb?x=1"]),
    ],
)
def test_requested_uri_matches(requested, registered):
    assert matches_registered(requested, registered)


@pytest.mark.parametrize(
    ("requested", "registered"),
    [
        ("https://claude.ai/api/mcp/auth_callback/", ["https://claude.ai/api/mcp/auth_callback"]),
        ("https://example.com:8443/cb", ["https://example.com/cb"]),
        ("https://example.com/cb?x=2", ["https://example.com/cb?x=1"]),
        ("http://localhost:51234/other", ["http://localhost/callback"]),
        ("http://localhost:51234/callback?x=1", ["http://localhost/callback"]),
        ("http://127.0.0.1:51234/callback", ["http://localhost/callback"]),
        ("http://localhost:51234/callback", ["http://127.0.0.1/callback"]),
        ("https://localhost:51234/callback", ["http://localhost/callback"]),
        ("http://localhost:51234/callback", ["https://localhost/callback"]),
        ("cursor://a/b:1", ["cursor://a/b"]),
        ("http://example.com:81/cb", ["http://example.com/cb"]),
        ("https://evil.test/cb", []),
    ],
)
def test_requested_uri_does_not_match(requested, registered):
    assert not matches_registered(requested, registered)
