"""Catalog of one-time purchasable products.

This is the single source of truth for what can be bought outside of
subscriptions. Checkout builds Stripe line items from it (inline price_data,
so no Stripe dashboard setup is needed), and the webhook re-validates the paid
amount against it. Replace the placeholder products with your own, and grant
or revoke whatever they unlock in app/api/hooks/purchases.py.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    id: str  # stable slug stored on Purchase rows; never reuse an id for a different product
    name: str
    description: str
    amount_cents: int
    currency: str  # ISO 4217, lowercase (e.g. "eur")


PRODUCTS: tuple[Product, ...] = (
    Product(
        id="starter-pack",
        name="Starter pack",
        description="Placeholder one-time product. Edit app/core/purchases.py.",
        amount_cents=1_000,
        currency="eur",
    ),
    Product(
        id="pro-pack",
        name="Pro pack",
        description="Placeholder one-time product. Edit app/core/purchases.py.",
        amount_cents=5_000,
        currency="eur",
    ),
)

_PRODUCTS_BY_ID: dict[str, Product] = {p.id: p for p in PRODUCTS}


def get_product(product_id: str) -> Product:
    """Return the catalog product with this id, or raise ``ValueError``.

    The message names the allowed ids rather than echoing the bad value so it
    can be shown to users as-is.
    """
    product = _PRODUCTS_BY_ID.get(product_id)
    if product is None:
        raise ValueError(f"product_id must be one of {sorted(_PRODUCTS_BY_ID)}")
    return product
