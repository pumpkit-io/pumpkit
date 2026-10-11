from fastapi import APIRouter, Request, status
from fastapi.responses import RedirectResponse

from pumpkit.core.config import settings
from pumpkit.core.rate_limit import limiter
from pumpkit.support.schemas import AnalyticsSettings, InstanceResponse, SignInMethod

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


@router.get("/instance", response_model=InstanceResponse)
@limiter.limit("120/minute")
async def instance(request: Request) -> InstanceResponse:
    """Public: every visitor's frontend reads it before rendering, signed in or not."""
    posthog_key = settings.POSTHOG_PROJECT_API_KEY
    analytics = (
        AnalyticsSettings(
            key=posthog_key, host=settings.POSTHOG_HOST, ui_host=settings.POSTHOG_UI_HOST
        )
        if posthog_key
        else None
    )
    sign_in_methods: list[SignInMethod] = ["magic_link"]
    if settings.is_google_configured():
        sign_in_methods.append("google")
    # TODO(#98): derive sells_plans and operator from their provider settings.
    return InstanceResponse(
        app_name=settings.APP_NAME,
        sells_plans=True,
        sign_in_methods=sign_in_methods,
        operator=None,
        analytics=analytics,
    )
