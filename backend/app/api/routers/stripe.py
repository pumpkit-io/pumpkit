from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.stripe as stripe_mediator
from app.api.dependencies import get_current_user
from app.core.billing_gateway import BillingGateway, get_billing_gateway
from app.core.rate_limit import limiter
from app.db.models import User
from app.db.session import get_async_db
from app.schemas.stripe import (
    BillingPortalResponse,
    CheckoutRequest,
    CheckoutResponse,
    PricesListResponse,
    SubscriptionMeResponse,
    TrialRequest,
    TrialResponse,
)

router = APIRouter(tags=["stripe"])


@router.get(
    "/stripe/me",
    response_model=SubscriptionMeResponse,
    status_code=status.HTTP_200_OK,
)
async def get_stripe_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> SubscriptionMeResponse:
    return await stripe_mediator.get_subscription_me(db=db, user=current_user)


@router.get(
    "/stripe/prices",
    response_model=PricesListResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("30/minute")
async def list_stripe_prices(
    request: Request,
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> PricesListResponse:
    return await stripe_mediator.list_prices(gateway=gateway)


@router.post(
    "/stripe/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("20/minute")
async def create_stripe_checkout(
    request: Request,
    checkout_request: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> CheckoutResponse:
    return await stripe_mediator.create_checkout_session(
        db=db, gateway=gateway, user=current_user, checkout_request=checkout_request
    )


@router.post(
    "/stripe/billing-portal",
    response_model=BillingPortalResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("20/minute")
async def create_stripe_billing_portal(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> BillingPortalResponse:
    return await stripe_mediator.create_billing_portal_session(
        db=db, gateway=gateway, user=current_user
    )


@router.post(
    "/stripe/trial",
    response_model=TrialResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("5/minute")
async def start_stripe_trial(
    request: Request,
    trial_request: TrialRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> TrialResponse:
    return await stripe_mediator.start_trial(
        db=db, gateway=gateway, user=current_user, trial_request=trial_request
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
    # before re-raising, so unexpected errors reach the global handler as a 500
    # and Stripe retries the event.
    await stripe_mediator.handle_webhook(
        db=db, gateway=gateway, payload=payload, signature=signature
    )

    return JSONResponse(content={"received": True}, status_code=status.HTTP_200_OK)
