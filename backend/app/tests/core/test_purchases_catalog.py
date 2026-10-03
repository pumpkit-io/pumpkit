import pytest

from app.core.purchases import PRODUCTS, get_product


def test_catalog_ids_are_unique_and_amounts_positive():
    ids = [p.id for p in PRODUCTS]
    assert len(ids) == len(set(ids)) >= 1
    assert all(p.amount_cents > 0 for p in PRODUCTS)
    assert all(p.currency == p.currency.lower() and len(p.currency) == 3 for p in PRODUCTS)


def test_get_product_known_and_unknown():
    assert get_product(PRODUCTS[0].id) is PRODUCTS[0]
    with pytest.raises(ValueError, match="product_id must be one of"):
        get_product("nope")
