from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse

from pumpkit.billing import service as billing_service
from pumpkit.core.config import settings
from pumpkit.core.providers import require_provider
from pumpkit.core.rate_limit import limiter
from pumpkit.support.schemas import (
    AnalyticsSettings,
    InstanceResponse,
    OperatorDetails,
    SignInMethod,
)

router = APIRouter(tags=["support"])


def _operator_details() -> Optional[OperatorDetails]:
    """The Operator details group (ADR 0011), or None when the Instance has none."""
    if not settings.is_operator_configured():
        return None
    return OperatorDetails(
        name=settings.OPERATOR_NAME or "",
        address=settings.OPERATOR_ADDRESS or "",
        vat_id=settings.OPERATOR_VAT_ID or None,
        rea=settings.OPERATOR_REA or None,
        share_capital=settings.OPERATOR_SHARE_CAPITAL or None,
        pec=settings.OPERATOR_PEC or None,
        support_email=settings.SUPPORT_EMAIL or "",
    )


@router.get(
    "/support/contact",
    status_code=status.HTTP_303_SEE_OTHER,
    dependencies=[Depends(require_provider(settings.is_operator_configured))],
)
@limiter.limit("60/minute")
async def support_contact(request: Request) -> RedirectResponse:
    """
    303-redirect to a mailto: link for the support address; 404 without Operator details.
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
    # The browser's analytics follow the key alone; POSTHOG_ENABLED gates only backend events.
    analytics = (
        AnalyticsSettings(
            key=settings.POSTHOG_PROJECT_API_KEY or "",
            host=settings.POSTHOG_HOST,
            ui_host=settings.POSTHOG_UI_HOST,
        )
        if settings.is_posthog_configured()
        else None
    )
    sign_in_methods: list[SignInMethod] = ["magic_link"]
    if settings.is_google_configured():
        sign_in_methods.append("google")
    return InstanceResponse(
        app_name=settings.APP_NAME,
        sells_plans=billing_service.sells_plans(),
        sign_in_methods=sign_in_methods,
        operator=_operator_details(),
        analytics=analytics,
    )
