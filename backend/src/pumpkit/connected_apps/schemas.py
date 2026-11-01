import unicodedata
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from pumpkit.connected_apps.service.redirect_uris import validate_redirect_uri

DEFAULT_CLIENT_NAME = "Unnamed app"
# Control, format (bidi overrides, zero-width) and line-separator characters, which let a
# name look like another app's on the consent page.
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})


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


ClientAuthMethod = Literal["none", "client_secret_post", "client_secret_basic"]
GrantType = Literal["authorization_code", "refresh_token"]


_MAX_URL_LENGTH = 2048


def _require_https(url: str) -> str:
    if not url.startswith("https://"):
        raise ValueError("must be an https URL")
    return url


_HttpsUrl = Annotated[
    str, StringConstraints(max_length=_MAX_URL_LENGTH), AfterValidator(_require_https)
]


class ClientRegistrationRequest(BaseModel):
    """RFC 7591 client metadata. Fields Pumpkit does not use, `scope` included, are ignored."""

    model_config = ConfigDict(extra="ignore")

    redirect_uris: Annotated[
        list[Annotated[str, AfterValidator(validate_redirect_uri)]],
        Field(min_length=1, max_length=10),
    ]
    client_name: Annotated[str, StringConstraints(max_length=100)] = DEFAULT_CLIENT_NAME
    # Stored and never fetched or rendered, so neither can pull a third party's content in.
    client_uri: Optional[_HttpsUrl] = None
    logo_uri: Optional[_HttpsUrl] = None
    token_endpoint_auth_method: ClientAuthMethod = "client_secret_basic"
    grant_types: list[GrantType] = ["authorization_code", "refresh_token"]
    response_types: list[Literal["code"]] = ["code"]
    software_id: Optional[Annotated[str, StringConstraints(max_length=200)]] = None
    software_version: Optional[Annotated[str, StringConstraints(max_length=200)]] = None

    @field_validator("client_name", mode="before")
    @classmethod
    def _clean_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        visible = "".join(c for c in value if unicodedata.category(c) not in _HIDDEN_CATEGORIES)
        return visible.strip() or DEFAULT_CLIENT_NAME

    @model_validator(mode="after")
    def _grants_include_authorization_code(self) -> "ClientRegistrationRequest":
        if "authorization_code" not in self.grant_types:
            raise ValueError("grant_types must include authorization_code")
        return self


class ClientRegistrationResponse(BaseModel):
    client_id: str
    client_id_issued_at: int
    client_secret: Optional[str] = None
    client_secret_expires_at: Optional[int] = None
    redirect_uris: list[str]
    client_name: str
    token_endpoint_auth_method: ClientAuthMethod
    grant_types: list[GrantType]
    response_types: list[Literal["code"]]
    client_uri: Optional[str] = None
    logo_uri: Optional[str] = None
    software_id: Optional[str] = None
    software_version: Optional[str] = None


class ConsentClient(BaseModel):
    name: str
    # The metadata document URL's host; None for an app that registered itself, so is unverified.
    verified_domain: Optional[str]
    # None when the app runs on the User's computer: a loopback or app-scheme redirect.
    redirect_host: Optional[str]
    is_local: bool


class AuthorizationDetailsResponse(BaseModel):
    """What the consent page shows about a pending request."""

    client: ConsentClient
    scope: str
    expires_at: datetime


class RedirectResponseBody(BaseModel):
    """Where the consent page sends the browser after the User decides."""

    redirect_url: str
