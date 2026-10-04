"""
The Sessions module: starts, rotates and ends a User's Sessions.

Every Sign-in method starts a Session here, `/refresh-token` rotates it and
`/logout` ends it. This module alone owns the token claims, the refresh cookie
(name, `__Host-` prefix, attributes), the callback fragment format, and rotation
with reuse detection. It flushes and never commits: the calling mediator commits
once, including after a refusal, because some refusals revoke a Session.
"""

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Union
from urllib.parse import urlencode

from fastapi import Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.refresh_tokens as refresh_tokens_service
import app.api.services.users as user_service
from app.core.config import settings
from app.core.datetimes import as_utc
from app.core.ids import ulid_with_prefix
from app.core.logger import logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_token,
    verify_refresh_token,
)
from app.db.models import RefreshToken, SignInMethod, User

# Responses that carry credentials must not be cached (OAuth 2.0, RFC 6749 §5.1).
_NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _refresh_cookie_name() -> str:
    # In production the "__Host-" prefix makes the browser accept the cookie only
    # over HTTPS, with path "/" and no domain attribute.
    return "__Host-refresh_token" if settings.is_env_production() else "refresh_token"


@dataclass(frozen=True)
class ClientInfo:
    """Where a Session's request came from, kept on its refresh tokens for audit."""

    ip: Optional[str]
    user_agent: Optional[str]

    @classmethod
    def from_request(cls, request: Request) -> "ClientInfo":
        return cls(
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


def read_refresh_cookie(request: Request) -> Optional[str]:
    """The refresh cookie this browser presents, if any."""
    return request.cookies.get(_refresh_cookie_name())


@dataclass(frozen=True)
class IssuedSession:
    """A Session's fresh credentials. It renders itself as a JSON body or a callback redirect."""

    access_token: str
    access_token_expires_at: datetime
    refresh_token: str

    def as_json_response(self) -> JSONResponse:
        response = JSONResponse(
            content=self._access_token_fields(),
            status_code=status.HTTP_200_OK,
            headers=_NO_STORE_HEADERS,
        )
        self._set_refresh_cookie(response)
        return response

    def as_callback_redirect(self, callback_path: str) -> RedirectResponse:
        """
        A 303 to a frontend callback page (e.g. `/auth/magic-link/callback`) carrying
        the access token and its expiry in the URL fragment, which never reaches a server.
        """
        url = f"{settings.FRONTEND_URL}{callback_path}#{urlencode(self._access_token_fields())}"
        response = RedirectResponse(
            url=url, status_code=status.HTTP_303_SEE_OTHER, headers=_NO_STORE_HEADERS
        )
        self._set_refresh_cookie(response)
        return response

    def _access_token_fields(self) -> dict[str, str]:
        return {
            "access_token": self.access_token,
            "token_type": "Bearer",
            "expires_at": self.access_token_expires_at.isoformat(),
        }

    def _set_refresh_cookie(self, response: Union[JSONResponse, RedirectResponse]) -> None:
        response.set_cookie(
            key=_refresh_cookie_name(),
            value=self.refresh_token,
            max_age=settings.COOKIE_MAX_AGE_SECONDS,
            httponly=True,  # Out of reach of page scripts (XSS)
            secure=settings.is_env_production(),
            samesite="lax",
            path="/",
        )


class RefusalReason(enum.Enum):
    """Why the Sessions module refused to issue a Session."""

    MISSING = "missing"  # No refresh cookie was presented
    INVALID = "invalid"  # Unknown, expired, revoked or malformed refresh token
    REUSED = "reused"  # An already-rotated refresh token: its whole Session is revoked


@dataclass(frozen=True)
class SessionRefusal:
    """A refused Start or Rotate. Commit before responding: a refusal may have revoked Sessions."""

    reason: RefusalReason

    @property
    def code(self) -> str:
        """The machine-readable code the frontend sees."""
        return "invalid_refresh_token"

    def as_json_response(self) -> JSONResponse:
        """The 401 answer to a refused refresh."""
        return JSONResponse(
            content={"detail": self.code},
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )

    def as_sign_in_redirect(self) -> RedirectResponse:
        """The answer to a refused browser sign-in: the sign-in page with the refusal code."""
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/login?error={self.code}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


SessionResult = Union[IssuedSession, SessionRefusal]


async def start(
    db: AsyncSession, *, user: User, sign_in_method: SignInMethod, client: ClientInfo
) -> SessionResult:
    """Start a new Session for a User who has just proven who they are."""
    issued, _ = await _issue(
        db,
        user=user,
        sign_in_method=sign_in_method,
        session_id=ulid_with_prefix("session"),
        client=client,
    )
    return issued


async def rotate(
    db: AsyncSession, *, refresh_cookie: Optional[str], client: ClientInfo
) -> SessionResult:
    """
    Exchange a refresh cookie for new credentials in the same Session.
    Presenting an already-rotated refresh token revokes that whole Session.
    """
    if not refresh_cookie:
        return SessionRefusal(RefusalReason.MISSING)

    claims = verify_refresh_token(token=refresh_cookie)
    user_id = claims.get("sub") if claims else None
    if not user_id:
        return SessionRefusal(RefusalReason.INVALID)

    # Lock the row so two concurrent refreshes can't both rotate the same token.
    presented = await refresh_tokens_service.get_refresh_token_by_hash(
        db=db, token_hash=hash_token(refresh_cookie), lock_for_update=True
    )
    if presented is None or presented.user_id != user_id:
        return SessionRefusal(RefusalReason.INVALID)

    if presented.rotated_at is not None:
        # Someone holds a copy of a token that was already exchanged: likely theft.
        logger.error(
            "Refresh token reuse detected: revoking Session (session_id=%s, user_id=%s)",
            presented.session_id,
            presented.user_id,
        )
        await refresh_tokens_service.revoke_session(db=db, session_id=presented.session_id)
        return SessionRefusal(RefusalReason.REUSED)

    if presented.is_revoked or as_utc(presented.expires_at) <= datetime.now(timezone.utc):
        return SessionRefusal(RefusalReason.INVALID)

    user = await user_service.get_user_by_id(db=db, user_id=user_id)
    if user is None:
        return SessionRefusal(RefusalReason.INVALID)

    issued, new_token = await _issue(
        db,
        user=user,
        sign_in_method=presented.sign_in_method,
        session_id=presented.session_id,
        client=client,
    )
    await refresh_tokens_service.mark_rotated(db=db, token=presented, replaced_by=new_token)
    return issued


async def end(db: AsyncSession, *, refresh_cookie: Optional[str]) -> None:
    """
    End the Session this refresh cookie belongs to, and only that one.
    A missing or unknown cookie means there is nothing to end, which is not an error.
    """
    if not refresh_cookie:
        return
    token = await refresh_tokens_service.get_refresh_token_by_hash(
        db=db, token_hash=hash_token(refresh_cookie)
    )
    if token is not None:
        await refresh_tokens_service.revoke_session(db=db, session_id=token.session_id)


def ended_session_response() -> JSONResponse:
    """The answer to a sign-out: success, with the refresh cookie cleared."""
    response = JSONResponse(
        content={"message": "Logged out successfully"}, status_code=status.HTTP_200_OK
    )
    response.delete_cookie(
        key=_refresh_cookie_name(),
        path="/",
        httponly=True,
        secure=settings.is_env_production(),
        samesite="lax",
    )
    return response


async def _issue(
    db: AsyncSession,
    *,
    user: User,
    sign_in_method: SignInMethod,
    session_id: str,
    client: ClientInfo,
) -> tuple[IssuedSession, RefreshToken]:
    # Claims identify the User by ID only: an email in a token goes stale and leaks.
    access_token = create_access_token(data={"sub": user.id})
    refresh_token = create_refresh_token(data={"sub": user.id})
    stored = await refresh_tokens_service.create_refresh_token(
        db=db,
        user_id=user.id,
        refresh_token=refresh_token,
        sign_in_method=sign_in_method,
        session_id=session_id,
        ip=client.ip,
        user_agent=client.user_agent,
    )
    issued = IssuedSession(
        access_token=access_token,
        access_token_expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        refresh_token=refresh_token,
    )
    return issued, stored
