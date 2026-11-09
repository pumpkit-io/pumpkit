from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.dependencies import get_current_user
from pumpkit.auth.models import User
from pumpkit.billing import mediator, service
from pumpkit.billing.allowance import sells_top_ups
from pumpkit.billing.gateway import BillingGateway, get_billing_gateway
from pumpkit.billing.schemas import (
    BillingMeResponse,
    BillingPortalResponse,
    CheckoutRequest,
    CheckoutResponse,
    CouponPreviewRequest,
    CouponPreviewResponse,
    CouponRedemptionRequest,
    CouponRedemptionResponse,
    PaidSignupPreviewRequest,
    PaidSignupPreviewResponse,
    PaidSignupRequest,
    PaidSignupResponse,
    PlansListResponse,
    TopUpCheckoutRequest,
)
from pumpkit.core.db.session import get_async_db
from pumpkit.core.providers import require_provider
from pumpkit.core.rate_limit import limiter
from pumpkit.core.time import Clock, get_clock

router = APIRouter(tags=["billing"], dependencies=[Depends(require_provider(service.sells_plans))])


@router.get(
    "/billing/me",
    response_model=BillingMeResponse,
    status_code=status.HTTP_200_OK,
)
async def get_billing_me(
    clock: Clock = Depends(get_clock),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> BillingMeResponse:
    return await mediator.get_billing_me(db=db, user=current_user, now=clock())


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
    clock: Clock = Depends(get_clock),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> CheckoutResponse:
    return await mediator.create_checkout_session(
        db=db, gateway=gateway, user=current_user, checkout_request=checkout_request, clock=clock
    )


@router.post(
    "/billing/top-ups/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_provider(sells_top_ups))],
)
@limiter.limit("20/minute")
async def create_top_up_checkout(
    request: Request,
    checkout_request: TopUpCheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
    clock: Clock = Depends(get_clock),
) -> CheckoutResponse:
    return await mediator.create_top_up_checkout(
        db=db, gateway=gateway, user=current_user, checkout_request=checkout_request, clock=clock
    )


@router.post(
    "/billing/subscribe-now",
    response_model=BillingMeResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("5/minute")
async def subscribe_now(
    request: Request,
    clock: Clock = Depends(get_clock),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> BillingMeResponse:
    return await mediator.subscribe_now(db=db, gateway=gateway, user=current_user, clock=clock)


@router.post(
    "/billing/portal",
    response_model=BillingPortalResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("20/minute")
async def create_billing_portal(
    request: Request,
    clock: Clock = Depends(get_clock),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> BillingPortalResponse:
    return await mediator.create_billing_portal_session(
        db=db, gateway=gateway, user=current_user, clock=clock
    )


@router.post("/stripe/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    clock: Clock = Depends(get_clock),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> JSONResponse:
    # Signature verification requires the raw, unmodified request body.
    payload = await request.body()
    signature = request.headers.get("stripe-signature")

    # handle_webhook owns the transaction and rolls back before re-raising, so errors reach
    # the global handlers (502 if Stripe failed during the sync, else 500) and Stripe retries.
    await mediator.handle_webhook(
        db=db, gateway=gateway, payload=payload, signature=signature, now=clock()
    )

    return JSONResponse(content={"received": True}, status_code=status.HTTP_200_OK)


@router.post("/billing/coupons/preview", response_model=CouponPreviewResponse)
@limiter.limit("20/minute")
async def preview_coupon(
    request: Request,
    preview_request: CouponPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
    clock: Clock = Depends(get_clock),
) -> CouponPreviewResponse:
    return await mediator.preview_coupon(
        db=db,
        gateway=gateway,
        user=current_user,
        code=preview_request.code.get_secret_value(),
        now=clock(),
    )


@router.post("/billing/coupons/redemptions", response_model=CouponRedemptionResponse)
@limiter.limit("20/minute")
async def redeem_coupon(
    request: Request,
    redemption: CouponRedemptionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
    clock: Clock = Depends(get_clock),
) -> CouponRedemptionResponse:
    return await mediator.redeem_coupon(db, gateway, current_user, request=redemption, clock=clock)


@router.get("/billing/coupons/redemptions/{operation_id}", response_model=CouponRedemptionResponse)
async def lookup_coupon_redemption(
    operation_id: str,
    gateway: BillingGateway = Depends(get_billing_gateway),
    clock: Clock = Depends(get_clock),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> CouponRedemptionResponse:
    return await mediator.lookup_coupon_redemption(
        db, gateway, current_user, operation_id=operation_id, clock=clock
    )


@router.post("/billing/cancel-renewal", response_model=BillingMeResponse)
async def cancel_renewal(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
    clock: Clock = Depends(get_clock),
) -> BillingMeResponse:
    return await mediator.cancel_renewal(db, gateway, current_user, clock=clock)


@router.post("/billing/paid-signups/preview", response_model=PaidSignupPreviewResponse)
@limiter.limit("20/minute")
async def preview_paid_signup(
    request: Request,
    signup_request: PaidSignupPreviewRequest,
    clock: Clock = Depends(get_clock),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> PaidSignupPreviewResponse:
    return await mediator.preview_paid_signup(
        db, gateway, current_user, plan_key=signup_request.plan_key, clock=clock
    )


@router.post("/billing/paid-signups", response_model=PaidSignupResponse)
@limiter.limit("20/minute")
async def create_paid_signup(
    request: Request,
    signup_request: PaidSignupRequest,
    clock: Clock = Depends(get_clock),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> PaidSignupResponse:
    return await mediator.create_paid_signup(
        db, gateway, current_user, request=signup_request, clock=clock
    )


@router.get("/billing/paid-signups/{operation_id}", response_model=PaidSignupResponse)
@limiter.limit("60/minute")
async def lookup_paid_signup(
    request: Request,
    operation_id: str,
    clock: Clock = Depends(get_clock),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> PaidSignupResponse:
    return await mediator.lookup_paid_signup(
        db, gateway, current_user, operation_id=operation_id, clock=clock
    )


@router.post("/billing/paid-signups/{operation_id}/cancel", response_model=PaidSignupResponse)
@limiter.limit("20/minute")
async def cancel_paid_signup(
    request: Request,
    operation_id: str,
    clock: Clock = Depends(get_clock),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
) -> PaidSignupResponse:
    return await mediator.lookup_paid_signup(
        db, gateway, current_user, operation_id=operation_id, clock=clock, cancel=True
    )
