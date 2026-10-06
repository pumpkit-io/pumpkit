from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.posts as posts_mediator
from app.api.dependencies import require_subscribed_user
from app.core.clock import Clock, get_clock
from app.core.llm import LLM, get_llm
from app.core.rate_limit import limiter
from app.db.models import User
from app.db.session import get_async_db
from app.schemas.posts import PostResponse, PostStartRequest

router = APIRouter(tags=["posts"])


@router.post("/posts", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def start_post(
    request: Request,
    start_request: PostStartRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    llm: LLM = Depends(get_llm),
    clock: Clock = Depends(get_clock),
) -> PostResponse:
    """Writes the first Version before answering, which takes two model calls."""
    return await posts_mediator.start_post(
        db=db, llm=llm, user=current_user, brief=start_request.brief, now=clock()
    )
