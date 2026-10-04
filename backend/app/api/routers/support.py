from fastapi import APIRouter, Request, status
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.rate_limit import limiter

router = APIRouter(tags=["support"])


@router.get(
    "/support/contact",
    status_code=status.HTTP_303_SEE_OTHER,
)
@limiter.limit("60/minute")
async def support_contact(request: Request) -> RedirectResponse:
    """
    303-redirect to a mailto: link for the support address. Browsers follow
    Location: mailto:... transparently, so the anchor on the frontend does
    not need to know the support address.
    """
    return RedirectResponse(
        url=f"mailto:{settings.RESEND_SUPPORT_ADDRESS}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
