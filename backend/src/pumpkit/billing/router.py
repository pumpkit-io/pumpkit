from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.dependencies import get_current_user
from pumpkit.auth.models import User
from pumpkit.billing import mediator, service
from pumpkit.billing.gateway import BillingGateway, get_billing_gateway
from pumpkit.billing.schemas import (
    BillingMeResponse,
    BillingPortalResponse,
    CheckoutRequest,
    CheckoutResponse,
    PlansListResponse,
)
from pumpkit.core.db.session import get_async_db
from pumpkit.core.providers import require_provider
from pumpkit.core.rate_limit import limiter

router = APIRouter(tags=["billing"], dependencies=[Depends(require_provider(service.sells_plans))])


@router.get(
    "/billing/me",
    response_model=BillingMeResponse,
    status_code=status.HTTP_200_OK,
)
async def get_billing_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> BillingMeResponse:
    return await mediator.get_billing_me(db=db, user=current_user)


@router.get(
    "/billing/plans",
    response_model=PlansListResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("30/minute")
async def list_billing_plans(
    request: Request,
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> PlansListResponse:
    # Public: the landing page lists Plans to signed-out visitors.
    return await mediator.list_plans(gateway=gateway)


@router.post(
    "/billing/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("20/minute")
async def create_billing_checkout(
    request: Request,
    checkout_request: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> CheckoutResponse:
    return await mediator.create_checkout_session(
        db=db, gateway=gateway, user=current_user, checkout_request=checkout_request
    )


@router.post(
    "/billing/portal",
    response_model=BillingPortalResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("20/minute")
async def create_billing_portal(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> BillingPortalResponse:
    return await mediator.create_billing_portal_session(db=db, gateway=gateway, user=current_user)


@router.post("/stripe/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> JSONResponse:
    # Signature verification requires the raw, unmodified request body.
    payload = await request.body()
    signature = request.headers.get("stripe-signature")

    # handle_webhook owns the transaction and rolls back before re-raising, so errors reach
    # the global handlers (502 if Stripe failed during the sync, else 500) and Stripe retries.
    await mediator.handle_webhook(db=db, gateway=gateway, payload=payload, signature=signature)

    return JSONResponse(content={"received": True}, status_code=status.HTTP_200_OK)
