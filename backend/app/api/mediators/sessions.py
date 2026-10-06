from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.sessions as sessions


async def refresh_token(request: Request, db: AsyncSession) -> JSONResponse:
    """
    Rotate the Session of the presented refresh cookie, or answer 401 on any refusal.
    """
    result = await sessions.rotate(
        db,
        refresh_cookie=sessions.read_refresh_cookie(request),
        client=sessions.ClientInfo.from_request(request),
    )
    # Commit refusals too: a reused refresh token revokes its Session, and that
    # must persist even though this request answers 401.
    await db.commit()
    return result.as_json_response()


async def logout(request: Request, db: AsyncSession) -> JSONResponse:
    """
    End only the Session of the presented refresh cookie. Signing out always succeeds;
    a failure while revoking is unexpected and reaches the global handler.
    """
    await sessions.end(db, refresh_cookie=sessions.read_refresh_cookie(request))
    await db.commit()
    return sessions.ended_session_response()
