from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.billing.dependencies import require_subscribed_user
from pumpkit.core.db.session import get_async_db
from pumpkit.core.rate_limit import limiter
from pumpkit.core.time import Clock, get_clock
from pumpkit.posts import mediator
from pumpkit.posts.llm import LLM, get_llm
from pumpkit.posts.schemas import WRITE_RATE, PostResponse, PostStartRequest

# Feedback on a Post is served from scheduling, which knows whether the Post takes it.
router = APIRouter(tags=["posts"])


@router.post("/posts", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(WRITE_RATE)
async def start_post(
    request: Request,
    start_request: PostStartRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    llm: LLM = Depends(get_llm),
    clock: Clock = Depends(get_clock),
) -> PostResponse:
    """Writes the first Version before answering, which takes two model calls."""
    return await mediator.start_post(
        db=db,
        llm=llm,
        user=current_user,
        brief=start_request.brief,
        format=start_request.format,
        now=clock(),
    )
