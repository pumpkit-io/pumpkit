from datetime import datetime
from typing import Optional

from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.core.config import settings
from pumpkit.x_connection import sign_in_service
from pumpkit.x_connection.service import LIFETIME
from pumpkit.x_connection.x_publisher import X_SIGN_IN_SCOPES, XPublisher, code_challenge_for

BROWSER_COOKIE = "x_sign_in_browser"


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
        key=BROWSER_COOKIE,
        value=started.browser_secret,
        max_age=int(LIFETIME.total_seconds()),
        path="/",
        httponly=True,
        secure=settings.serves_https(),
        samesite="lax",
    )
    return response
