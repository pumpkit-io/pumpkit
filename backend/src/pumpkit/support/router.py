from fastapi import APIRouter, Request, status
from fastapi.responses import RedirectResponse

from pumpkit.core.config import settings
from pumpkit.core.rate_limit import limiter

router = APIRouter(tags=["support"])


@router.get(
    "/support/contact",
    status_code=status.HTTP_303_SEE_OTHER,
)
@limiter.limit("60/minute")
async def support_contact(request: Request) -> RedirectResponse:
    """
    303-redirect to a mailto: link for the support address.
    Browsers follow a mailto: Location, so the frontend never needs the address.
    """
    return RedirectResponse(
        url=f"mailto:{settings.SUPPORT_EMAIL}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
