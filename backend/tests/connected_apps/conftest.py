import pytest
import pytest_asyncio

REDIRECT = "http://127.0.0.1:33418/callback"
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
MCP_URL = "http://localhost:5173/api/v1/mcp"


@pytest_asyncio.fixture
async def oauth_client(new_browser) -> str:
    """The id of a public app registered through Dynamic Client Registration."""
    response = await new_browser().post(
        "/api/v1/oauth/register",
        json={
            "redirect_uris": [REDIRECT],
            "client_name": "Gemini CLI",
            "token_endpoint_auth_method": "none",
        },
    )
    return response.json()["client_id"]


@pytest.fixture
def authorize_params(oauth_client) -> dict[str, str]:
    """A valid authorize request from `oauth_client`; tests override or drop fields."""
    return {
        "client_id": oauth_client,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": "xyz",
    }
