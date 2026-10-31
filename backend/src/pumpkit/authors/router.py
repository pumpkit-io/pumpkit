from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.dependencies import get_current_user
from pumpkit.auth.models import User
from pumpkit.authors import mediator
from pumpkit.authors.schemas import (
    WRITE_RATE,
    AuthorDirectoryResponse,
    InspirationAuthorAddRequest,
    InspirationAuthorResponse,
    InspirationAuthorsListResponse,
)
from pumpkit.authors.x_reader import XReader, get_x_reader
from pumpkit.billing.dependencies import require_subscribed_user
from pumpkit.core.db.session import get_async_db
from pumpkit.core.rate_limit import limiter
from pumpkit.core.time import Clock, get_clock

router = APIRouter(tags=["inspiration-authors"])


@router.get(
    "/author-directory",
    response_model=AuthorDirectoryResponse,
    status_code=status.HTTP_200_OK,
)
async def list_author_directory(
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
) -> AuthorDirectoryResponse:
    return await mediator.list_directory(db=db)


@router.get(
    "/inspiration-authors",
    response_model=InspirationAuthorsListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_inspiration_authors(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> InspirationAuthorsListResponse:
    return await mediator.list_authors(db=db, user=current_user)


@router.post(
    "/inspiration-authors",
    response_model=InspirationAuthorResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(WRITE_RATE)
async def add_inspiration_author(
    request: Request,
    add_request: InspirationAuthorAddRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    reader: XReader = Depends(get_x_reader),
    clock: Clock = Depends(get_clock),
) -> InspirationAuthorResponse:
    return await mediator.add_author(
        db=db, reader=reader, user=current_user, handle=add_request.handle, now=clock()
    )


@router.post(
    "/inspiration-authors/{handle}/refresh",
    response_model=InspirationAuthorResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit(WRITE_RATE)
async def refresh_inspiration_author(
    request: Request,
    handle: str,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    reader: XReader = Depends(get_x_reader),
    clock: Clock = Depends(get_clock),
) -> InspirationAuthorResponse:
    return await mediator.refresh_author(
        db=db, reader=reader, user=current_user, handle=handle, now=clock()
    )


@router.delete("/inspiration-authors/{handle}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_inspiration_author(
    handle: str,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    await mediator.remove_author(db=db, user=current_user, handle=handle)
