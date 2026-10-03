from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.db.models import PurchaseStatus


class ProductResponse(BaseModel):
    id: str
    name: str
    description: str
    amount_cents: int
    currency: str


class ProductsListResponse(BaseModel):
    data: list[ProductResponse]


class PurchaseCheckoutRequest(BaseModel):
    product_id: str = Field(..., min_length=1)


class PurchaseCheckoutResponse(BaseModel):
    url: str
    session_id: str


class PurchaseResponse(BaseModel):
    id: str
    product_id: str
    status: PurchaseStatus
    currency: str
    amount_subtotal_cents: int
    amount_total_cents: Optional[int]
    refunded_amount_cents: int
    created_at: datetime


class PurchasesListResponse(BaseModel):
    data: list[PurchaseResponse]
