from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.billing import service as billing_service
from pumpkit.core.config import settings
from pumpkit.core.db.health import database_is_reachable
from pumpkit.core.db.session import get_async_db
from pumpkit.core.providers import require_provider
from pumpkit.core.rate_limit import limiter
from pumpkit.support.schemas import (
    AnalyticsSettings,
    HealthResponse,
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
        vat_id=settings.OPERATOR_VAT_ID or None,
    )


@router.get(
    "/support/contact",
    status_code=status.HTTP_303_SEE_OTHER,
    dependencies=[Depends(require_provider(settings.has_support_email))],
)
@limiter.limit("60/minute")
async def support_contact(request: Request) -> RedirectResponse:
    """
    303-redirect to a mailto: link for the support address; 404 without SUPPORT_EMAIL.
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
        support_email=settings.SUPPORT_EMAIL or None,
        analytics=analytics,
        x_connection=settings.is_x_configured(),
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(db: AsyncSession = Depends(get_async_db)) -> HealthResponse | JSONResponse:
    """Public and not rate limited: Self-hosters, their agents and container healthchecks poll it."""
    if await database_is_reachable(db):
        return HealthResponse(status="ok")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=HealthResponse(status="unavailable").model_dump(),
    )
