from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.purchases as purchases_mediator
import app.api.services.purchases as purchases_service
import app.api.services.users as user_service
from app.core.purchases import PRODUCTS
from app.core.rate_limit import limiter
from app.db.models import User
from app.db.session import get_async_db
from app.schemas.billing import (
    ProductResponse,
    ProductsListResponse,
    PurchaseCheckoutRequest,
    PurchaseCheckoutResponse,
    PurchaseResponse,
    PurchasesListResponse,
)

router = APIRouter(tags=["billing"])


@router.get(
    "/billing/products", response_model=ProductsListResponse, status_code=status.HTTP_200_OK
)
async def list_products(
    current_user: User = Depends(user_service.get_user),
) -> ProductsListResponse:
    return ProductsListResponse(
        data=[
            ProductResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                amount_cents=p.amount_cents,
                currency=p.currency,
            )
            for p in PRODUCTS
        ]
    )


@router.post(
    "/billing/purchases/checkout",
    response_model=PurchaseCheckoutResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("20/minute")
async def create_purchase_checkout(
    request: Request,
    checkout_request: PurchaseCheckoutRequest,
    current_user: User = Depends(user_service.get_user),
    db: AsyncSession = Depends(get_async_db),
) -> PurchaseCheckoutResponse:
    return await purchases_mediator.create_checkout_session(
        db, user=current_user, product_id=checkout_request.product_id
    )


@router.get(
    "/billing/purchases", response_model=PurchasesListResponse, status_code=status.HTTP_200_OK
)
async def list_purchases(
    current_user: User = Depends(user_service.get_user),
    db: AsyncSession = Depends(get_async_db),
) -> PurchasesListResponse:
    purchases = await purchases_service.list_purchases_for_user(db, user_id=current_user.id)
    return PurchasesListResponse(
        data=[
            PurchaseResponse(
                id=p.id,
                product_id=p.product_id,
                status=p.status,
                currency=p.currency,
                amount_subtotal_cents=p.amount_subtotal_cents,
                amount_total_cents=p.amount_total_cents,
                refunded_amount_cents=p.refunded_amount_cents,
                created_at=p.created_at,
            )
            for p in purchases
        ]
    )
