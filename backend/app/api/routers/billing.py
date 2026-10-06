from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.billing as billing_mediator
from app.api.dependencies import get_current_user
from app.core.billing_gateway import BillingGateway, get_billing_gateway
from app.core.rate_limit import limiter
from app.db.models import User
from app.db.session import get_async_db
from app.schemas.billing import (
    BillingPortalResponse,
    CheckoutRequest,
    CheckoutResponse,
    PlansListResponse,
    SubscriptionMeResponse,
)

router = APIRouter(tags=["billing"])


@router.get(
    "/billing/me",
    response_model=SubscriptionMeResponse,
    status_code=status.HTTP_200_OK,
)
async def get_billing_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> SubscriptionMeResponse:
    return await billing_mediator.get_subscription_me(db=db, user=current_user)


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
    return await billing_mediator.list_plans(gateway=gateway)


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
    return await billing_mediator.create_checkout_session(
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
    return await billing_mediator.create_billing_portal_session(
        db=db, gateway=gateway, user=current_user
    )


@router.post("/stripe/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> JSONResponse:
    # Signature verification requires the raw, unmodified request body.
    payload = await request.body()
    signature = request.headers.get("stripe-signature")

    # handle_webhook owns the transaction: it commits on success and rolls back
    # before re-raising, so errors reach the global handlers (a 502 when Stripe
    # failed during the sync, else a 500) and Stripe retries the event.
    await billing_mediator.handle_webhook(
        db=db, gateway=gateway, payload=payload, signature=signature
    )

    return JSONResponse(content={"received": True}, status_code=status.HTTP_200_OK)
