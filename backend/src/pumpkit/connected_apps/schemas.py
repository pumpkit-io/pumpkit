from pydantic import BaseModel


class ProtectedResourceMetadata(BaseModel):
    """RFC 9728: tells an MCP client which authorization server guards the MCP URL."""

    resource: str
    authorization_servers: list[str]
    scopes_supported: list[str]
    bearer_methods_supported: list[str]
    resource_name: str


class AuthorizationServerMetadata(BaseModel):
    """RFC 8414: the endpoints and options an MCP client discovers at the origin."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str
    revocation_endpoint: str
    scopes_supported: list[str]
    response_types_supported: list[str]
    response_modes_supported: list[str]
    grant_types_supported: list[str]
    code_challenge_methods_supported: list[str]
    # `none` first: Claude and Codex pick the first method they support.
    token_endpoint_auth_methods_supported: list[str]
    revocation_endpoint_auth_methods_supported: list[str]
    authorization_response_iss_parameter_supported: bool
