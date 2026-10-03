from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

import app.api.mediators.support as support_mediator
from app.core.logger import logger
from app.core.rate_limit import limiter

router = APIRouter(tags=["support"])


@router.get(
    "/support/contact",
    status_code=status.HTTP_303_SEE_OTHER,
)
@limiter.limit("60/minute")
async def support_contact(request: Request) -> RedirectResponse:
    try:
        return support_mediator.build_contact_redirect_response()
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error building support contact redirect")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )
