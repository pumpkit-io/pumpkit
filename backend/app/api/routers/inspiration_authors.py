from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.inspiration_authors as inspiration_authors_mediator
import app.api.services.inspiration_authors as inspiration_authors_service
from app.api.dependencies import get_current_user, require_subscribed_user
from app.core.clock import Clock, get_clock
from app.core.rate_limit import limiter
from app.core.x_handles import normalize_handle
from app.core.x_reader import XReader, get_x_reader
from app.db.models import User
from app.db.session import get_async_db
from app.schemas.inspiration_authors import (
    InspirationAuthorAddRequest,
    InspirationAuthorResponse,
    InspirationAuthorsListResponse,
)

router = APIRouter(tags=["inspiration-authors"])


@router.get(
    "/inspiration-authors",
    response_model=InspirationAuthorsListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_inspiration_authors(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> InspirationAuthorsListResponse:
    summaries = await inspiration_authors_service.list_authors(db, user_id=current_user.id)
    return InspirationAuthorsListResponse(
        data=[
            InspirationAuthorResponse(
                handle=s.handle, last_fetched_at=s.last_fetched_at, post_count=s.post_count
            )
            for s in summaries
        ]
    )


@router.post(
    "/inspiration-authors",
    response_model=InspirationAuthorResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("20/minute")
async def add_inspiration_author(
    request: Request,
    add_request: InspirationAuthorAddRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    reader: XReader = Depends(get_x_reader),
    clock: Clock = Depends(get_clock),
) -> InspirationAuthorResponse:
    return await inspiration_authors_mediator.add_author(
        db=db, reader=reader, user=current_user, handle=add_request.handle, now=clock()
    )


@router.post(
    "/inspiration-authors/{handle}/refresh",
    response_model=InspirationAuthorResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("20/minute")
async def refresh_inspiration_author(
    request: Request,
    handle: str,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    reader: XReader = Depends(get_x_reader),
    clock: Clock = Depends(get_clock),
) -> InspirationAuthorResponse:
    return await inspiration_authors_mediator.refresh_author(
        db=db, reader=reader, user=current_user, handle=handle, now=clock()
    )


@router.delete("/inspiration-authors/{handle}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_inspiration_author(
    handle: str,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    not_listed = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="That handle isn't one of your Inspiration authors.",
    )
    try:
        normalized = normalize_handle(handle)
    except ValueError:
        raise not_listed
    author = await inspiration_authors_service.get_author(
        db, user_id=current_user.id, handle=normalized
    )
    if author is None:
        raise not_listed
    await inspiration_authors_service.remove_author(db, author)
    await db.commit()
