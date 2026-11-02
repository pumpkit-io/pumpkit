"""
`GoogleOAuthSignIn` against a local stand-in for a Google issuer, as an Emulator in the dev stack is one.
"""

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from pumpkit.auth.google_config import google_endpoints
from pumpkit.auth.google_sign_in import GoogleOAuthSignIn, GoogleSignInError
from pumpkit.core.config import settings

ISSUER = "http://google.emulate.pumpkit.localhost:1355"
NONCE = "nonce-1"


@dataclass
class StandInIssuer:
    """Serves a token endpoint and a JWKS like the Google Emulator; set `claims` to change the ID token."""

    url: str
    key: rsa.RSAPrivateKey = field(
        default_factory=lambda: rsa.generate_private_key(public_exponent=65537, key_size=2048)
    )
    claims: dict[str, Any] = field(default_factory=dict)
    token_forms: list[dict[str, list[str]]] = field(default_factory=list)

    def id_token(self) -> str:
        now = int(time.time())
        payload = {
            "iss": ISSUER,
            "aud": settings.GOOGLE_CLIENT_ID,
            "sub": "goog_alice",
            "email": "test@example.com",
            "email_verified": True,
            "given_name": "Test",
            "nonce": NONCE,
            "iat": now,
            "exp": now + 3600,
            **self.claims,
        }
        return jwt.encode(payload, self.key, algorithm="RS256", headers={"kid": "emulate-google-1"})

    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(RSAAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [{**jwk, "kid": "emulate-google-1", "use": "sig", "alg": "RS256"}]}


@pytest.fixture
def issuer(monkeypatch: pytest.MonkeyPatch) -> Iterator[StandInIssuer]:
    stand_in: StandInIssuer

    class Handler(BaseHTTPRequestHandler):
        def _answer(self, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path == "/oauth2/v3/certs":
                self._answer(stand_in.jwks())
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            if self.path != "/oauth2/token":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            stand_in.token_forms.append(parse_qs(self.rfile.read(length).decode()))
            self._answer({"access_token": "ya29.dev", "id_token": stand_in.id_token()})

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    stand_in = StandInIssuer(url=f"http://127.0.0.1:{server.server_port}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(settings, "GOOGLE_ISSUER", ISSUER)
    monkeypatch.setattr(settings, "GOOGLE_API_URL", stand_in.url)
    yield stand_in
    server.shutdown()
    server.server_close()


async def _exchange() -> Any:
    return await GoogleOAuthSignIn().exchange_code(
        code="auth-code", code_verifier="verifier", nonce=NONCE
    )


def test_without_overrides_google_sign_in_reaches_google_itself():
    endpoints = google_endpoints()

    assert endpoints.authorization == "https://accounts.google.com/o/oauth2/v2/auth"
    assert endpoints.token == "https://oauth2.googleapis.com/token"
    assert endpoints.issuers == ("accounts.google.com", "https://accounts.google.com")


async def test_an_emulator_issued_id_token_signs_in_with_its_claims(issuer):
    claims = await _exchange()

    assert claims.subject == "goog_alice"
    assert claims.email == "test@example.com"
    assert claims.given_name == "Test"
    # The code goes to the server-to-server URL, never the browser-facing issuer.
    assert issuer.token_forms[0]["code"] == ["auth-code"]
    assert issuer.token_forms[0]["code_verifier"] == ["verifier"]


async def test_an_id_token_from_another_issuer_is_refused(issuer):
    # Google's own issuer: an Emulator's stack trusts only the Emulator.
    issuer.claims = {"iss": "https://accounts.google.com"}

    with pytest.raises(GoogleSignInError):
        await _exchange()


async def test_an_id_token_for_another_client_is_refused(issuer):
    issuer.claims = {"aud": "someone-elses-client"}

    with pytest.raises(GoogleSignInError):
        await _exchange()


async def test_an_id_token_signed_with_another_key_is_refused(issuer):
    # The claims are valid and the kid matches: only the key differs from the one the JWKS serves.
    genuine = issuer.id_token()
    forged = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer.id_token = lambda: jwt.encode(
        jwt.decode(genuine, options={"verify_signature": False}),
        forged,
        algorithm="RS256",
        headers={"kid": "emulate-google-1"},
    )

    with pytest.raises(GoogleSignInError):
        await _exchange()
