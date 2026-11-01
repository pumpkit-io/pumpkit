import pytest

from pumpkit.core.config import settings
from tests.mcp_client import MCP, McpClient

ORIGIN = "http://localhost:5173"
RESOURCE_METADATA = f"{ORIGIN}/.well-known/oauth-protected-resource/api/v1/mcp"
CHALLENGE = f'Bearer resource_metadata="{RESOURCE_METADATA}", scope="pumpkit"'
PROTECTED_RESOURCE_PATHS = [
    "/.well-known/oauth-protected-resource/api/v1/mcp",
    "/.well-known/oauth-protected-resource",
]


@pytest.fixture
def browser(new_browser):
    return new_browser()


@pytest.mark.parametrize("path", PROTECTED_RESOURCE_PATHS)
async def test_the_protected_resource_metadata_names_the_mcp_url_and_its_issuer(browser, path):
    response = await browser.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "resource": f"{ORIGIN}/api/v1/mcp",
        "authorization_servers": [ORIGIN],
        "scopes_supported": ["pumpkit"],
        "bearer_methods_supported": ["header"],
        "resource_name": settings.APP_NAME,
    }


async def test_the_protected_resource_metadata_follows_public_url(browser, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://pumpkit.example.org")

    bodies = [(await browser.get(path)).json() for path in PROTECTED_RESOURCE_PATHS]

    assert bodies[0] == bodies[1]
    assert bodies[0]["resource"] == "https://pumpkit.example.org/api/v1/mcp"
    assert bodies[0]["authorization_servers"] == ["https://pumpkit.example.org"]


async def test_the_authorization_server_metadata_lists_the_endpoints_and_cimd(browser):
    response = await browser.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 200
    assert response.json() == {
        "issuer": ORIGIN,
        "authorization_endpoint": f"{ORIGIN}/api/v1/oauth/authorize",
        "token_endpoint": f"{ORIGIN}/api/v1/oauth/token",
        "registration_endpoint": f"{ORIGIN}/api/v1/oauth/register",
        "revocation_endpoint": f"{ORIGIN}/api/v1/oauth/revoke",
        "scopes_supported": ["pumpkit", "offline_access"],
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": [
            "none",
            "client_secret_post",
            "client_secret_basic",
        ],
        "revocation_endpoint_auth_methods_supported": [
            "none",
            "client_secret_post",
            "client_secret_basic",
        ],
        "authorization_response_iss_parameter_supported": True,
        "client_id_metadata_document_supported": True,
    }


async def test_the_issuer_is_public_url_exactly(browser, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://pumpkit.example.org")

    body = (await browser.get("/.well-known/oauth-authorization-server")).json()

    assert body["issuer"] == "https://pumpkit.example.org"
    assert body["token_endpoint"] == "https://pumpkit.example.org/api/v1/oauth/token"


async def test_openid_configuration_is_a_json_404(browser):
    response = await browser.get("/.well-known/openid-configuration")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"


async def test_a_post_without_a_credential_is_401_with_the_discovery_challenge(browser):
    response = await McpClient(browser, None).send("tools/list")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == CHALLENGE
    assert response.json() == {"detail": "Not authenticated"}


@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_a_get_or_delete_without_a_credential_is_401_with_the_discovery_challenge(
    browser, method
):
    response = await browser.request(method, MCP)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == CHALLENGE


async def test_a_refused_credential_adds_invalid_token_to_the_challenge(browser):
    response = await McpClient(browser, "pk_unknown").send("tools/list")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == (
        f'Bearer resource_metadata="{RESOURCE_METADATA}", scope="pumpkit", '
        'error="invalid_token", error_description="Could not validate credentials"'
    )
    assert response.json() == {"detail": "Could not validate credentials"}


@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_an_authenticated_get_or_delete_is_405_allowing_post(subscribed, mcp, method):
    response = await mcp.http.request(method, MCP, headers=mcp.headers())

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource/api/v1/mcp",
        "/.well-known/openid-configuration",
        "/api/v1/oauth/token",
        "/api/v1/oauth/register",
        "/api/v1/oauth/revoke",
        MCP,
    ],
)
async def test_a_preflight_on_a_client_facing_path_allows_any_origin_without_credentials(
    browser, path
):
    response = await browser.options(
        path,
        headers={
            "Origin": "https://inspector.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type, mcp-protocol-version",
        },
    )

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers
    allowed = response.headers["access-control-allow-headers"].lower()
    for name in ("authorization", "content-type", "mcp-protocol-version", "mcp-session-id"):
        assert name in allowed


async def test_responses_on_a_client_facing_path_expose_the_challenge_to_browsers(browser):
    response = await McpClient(browser, None).send("tools/list")

    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers
    exposed = response.headers["access-control-expose-headers"]
    assert "WWW-Authenticate" in exposed
    assert "Mcp-Session-Id" in exposed


@pytest.mark.parametrize(
    "path", ["/api/v1/oauth/authorize", "/api/v1/oauth/consent", "/api/v1/api-keys"]
)
async def test_other_paths_keep_the_strict_origin_policy(browser, path):
    response = await browser.options(
        path,
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert response.headers.get("access-control-allow-origin") != "*"
    assert "access-control-allow-origin" not in response.headers
