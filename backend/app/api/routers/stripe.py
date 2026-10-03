from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.stripe as stripe_mediator
import app.api.services.users as user_service
from app.core.logger import logger
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
    current_user: User = Depends(user_service.get_user),
    db: AsyncSession = Depends(get_async_db),
) -> SubscriptionMeResponse:
    try:
        return await stripe_mediator.get_subscription_me(db=db, user=current_user)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error while fetching subscription status")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )


@router.get(
    "/stripe/prices",
    response_model=PricesListResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("30/minute")
async def list_stripe_prices(request: Request) -> PricesListResponse:
    try:
        return await stripe_mediator.list_prices()
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error while listing Stripe prices")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )


@router.post(
    "/stripe/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("20/minute")
async def create_stripe_checkout(
    request: Request,
    checkout_request: CheckoutRequest,
    current_user: User = Depends(user_service.get_user),
    db: AsyncSession = Depends(get_async_db),
) -> CheckoutResponse:
    try:
        return await stripe_mediator.create_checkout_session(
            db=db, user=current_user, checkout_request=checkout_request
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error while creating Stripe checkout session")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )


@router.post(
    "/stripe/billing-portal",
    response_model=BillingPortalResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("20/minute")
async def create_stripe_billing_portal(
    request: Request,
    current_user: User = Depends(user_service.get_user),
    db: AsyncSession = Depends(get_async_db),
) -> BillingPortalResponse:
    try:
        return await stripe_mediator.create_billing_portal_session(db=db, user=current_user)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error while creating Stripe billing portal session")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
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
    current_user: User = Depends(user_service.get_user),
    db: AsyncSession = Depends(get_async_db),
) -> TrialResponse:
    try:
        return await stripe_mediator.start_trial(
            db=db, user=current_user, trial_request=trial_request
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error while starting Stripe trial")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )


@router.post("/stripe/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> JSONResponse:
    # Signature verification requires the raw, unmodified request body.
    payload = await request.body()
    signature = request.headers.get("stripe-signature")

    try:
        await stripe_mediator.handle_webhook(db=db, payload=payload, signature=signature)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error while handling Stripe webhook")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong processing the webhook.",
        )

    return JSONResponse(content={"received": True}, status_code=status.HTTP_200_OK)
