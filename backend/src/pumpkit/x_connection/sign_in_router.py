from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.core.db.session import get_async_db
from pumpkit.core.rate_limit import limiter
from pumpkit.core.time import Clock, get_clock
from pumpkit.x_connection import sign_in_mediator
from pumpkit.x_connection.schemas import XSignInStartQuery
from pumpkit.x_connection.x_publisher import XPublisher, get_x_publisher

# Staged until the X-only cutover; production assembly does not mount this router.
router = APIRouter(tags=["auth"])


@router.get("/login/x")
@limiter.limit("10/minute")
async def start_x_sign_in(
    request: Request,
    query: Annotated[XSignInStartQuery, Query()],
    db: AsyncSession = Depends(get_async_db),
    publisher: XPublisher = Depends(get_x_publisher),
    clock: Clock = Depends(get_clock),
) -> JSONResponse:
    return await sign_in_mediator.start_sign_in(
        db, publisher=publisher, now=clock(), return_to=query.return_to
    )
