from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from pumpkit.billing import service as billing_service
from pumpkit.core.config import settings
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
    name, address, support_email = (
        settings.OPERATOR_NAME,
        settings.OPERATOR_ADDRESS,
        settings.SUPPORT_EMAIL,
    )
    if not (name and address and support_email):
        return None
    return OperatorDetails(
        name=name,
        address=address,
        vat_id=settings.OPERATOR_VAT_ID or None,
        rea=settings.OPERATOR_REA or None,
        share_capital=settings.OPERATOR_SHARE_CAPITAL or None,
        pec=settings.OPERATOR_PEC or None,
        support_email=support_email,
    )


@router.get(
    "/support/contact",
    status_code=status.HTTP_303_SEE_OTHER,
)
@limiter.limit("60/minute")
async def support_contact(request: Request) -> RedirectResponse:
    """
    303-redirect to a mailto: link for the support address; 404 without Operator details.
    Browsers follow a mailto: Location, so the frontend never needs the address.
    """
    operator = _operator_details()
    if operator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return RedirectResponse(
        url=f"mailto:{operator.support_email}",
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
    return InstanceResponse(
        app_name=settings.APP_NAME,
        sells_plans=billing_service.sells_plans(),
        sign_in_methods=sign_in_methods,
        operator=_operator_details(),
        analytics=analytics,
    )
