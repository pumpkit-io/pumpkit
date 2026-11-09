from datetime import datetime
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.service import sessions, users
from pumpkit.auth.sign_up_allowlist import EMAIL_NOT_ALLOWED, may_sign_in
from pumpkit.core.config import settings
from pumpkit.x_connection import service, sign_in_service
from pumpkit.x_connection.service import LIFETIME
from pumpkit.x_connection.x_publisher import (
    X_SIGN_IN_SCOPES,
    XPermissionsRequiredError,
    XPublisher,
    XPublisherError,
    XReconnectNeededError,
    code_challenge_for,
)


def _browser_cookie_name() -> str:
    # Host-only prefixes prevent a sibling subdomain from planting a sign-in binding.
    return "__Host-x_sign_in_browser" if settings.serves_https() else "x_sign_in_browser"


async def start_sign_in(
    db: AsyncSession, *, publisher: XPublisher, now: datetime, return_to: Optional[str]
) -> JSONResponse:
    started = await sign_in_service.start(db, now=now, return_to=return_to)
    url = publisher.build_authorize_url(
        state=started.state,
        code_challenge=code_challenge_for(started.code_verifier),
        scopes=X_SIGN_IN_SCOPES,
    )
    await db.commit()
    response = JSONResponse(content={"url": url}, headers={"Cache-Control": "no-store"})
    response.set_cookie(
        key=_browser_cookie_name(),
        value=started.browser_secret,
        max_age=int(LIFETIME.total_seconds()),
        path="/",
        httponly=True,
        secure=settings.serves_https(),
        samesite="lax",
    )
    return response


async def complete_sign_in(
    db: AsyncSession,
    *,
    request: Request,
    publisher: XPublisher,
    now: datetime,
    state: str,
    code: Optional[str],
    error: Optional[str],
) -> JSONResponse:
    attempt = await sign_in_service.consume(
        db, state=state, browser_secret=request.cookies.get(_browser_cookie_name(), ""), now=now
    )
    # A failed exchange must not restore a spent browser-bound attempt.
    await db.commit()
    if attempt is None:
        return _failed("x_authorization_invalid")
    if error or not code:
        return _failed(
            "x_authorization_cancelled" if error == "access_denied" else "x_authorization_invalid"
        )
    try:
        tokens = await publisher.exchange_code(
            code=code,
            code_verifier=attempt.code_verifier,
            now=now,
            required_scopes=X_SIGN_IN_SCOPES,
        )
        account = await publisher.fetch_account(access_token=tokens.access_token, for_sign_in=True)
    except XPermissionsRequiredError:
        return _failed("x_permissions_required")
    except XReconnectNeededError:
        return _failed("x_authorization_invalid")
    except XPublisherError:
        return _failed("x_provider_failed", status_code=502)
    if account.confirmed_email is None:
        return _failed("x_email_required")
    if not may_sign_in(account.confirmed_email):
        return _failed(EMAIL_NOT_ALLOWED, status_code=403)
    user = await users.resolve_user_by_x_id(
        db,
        x_user_id=account.user_id,
        handle=account.handle,
        email=account.confirmed_email,
        display_name=account.display_name,
    )
    owner = await service.get_connection_by_x_user_id(db, x_user_id=account.user_id)
    if owner is not None and owner.user_id != user.id:
        await db.rollback()
        return _failed("x_account_unavailable", status_code=409)
    issued = await sessions.start(
        db, user=user, sign_in_method="x", client=sessions.ClientInfo.from_request(request)
    )
    if isinstance(issued, sessions.SessionRefusal):
        await db.rollback()
        return _failed(issued.code, status_code=401)
    try:
        await service.save_connection(db, user_id=user.id, account=account, tokens=tokens, now=now)
    except IntegrityError:
        await db.rollback()
        return _failed("x_account_unavailable", status_code=409)
    await db.commit()
    response = issued.as_json_response()
    _clear_browser_cookie(response)
    return response


def _failed(code: str, *, status_code: int = 400) -> JSONResponse:
    response = JSONResponse(
        {"detail": code}, status_code=status_code, headers={"Cache-Control": "no-store"}
    )
    _clear_browser_cookie(response)
    return response


def _clear_browser_cookie(response: JSONResponse) -> None:
    response.delete_cookie(
        _browser_cookie_name(),
        path="/",
        httponly=True,
        secure=settings.serves_https(),
        samesite="lax",
    )
