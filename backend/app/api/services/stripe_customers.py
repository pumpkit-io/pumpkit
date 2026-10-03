import asyncio

import stripe
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.stripe as stripe_service
from app.core.config import settings
from app.core.logger import logger
from app.db.models import User

stripe.api_key = settings.STRIPE_SECRET_KEY


async def ensure_stripe_customer(db: AsyncSession, user: User) -> str:
    """
    Return the user's Stripe customer ID, creating one via Stripe and persisting
    it on the user row if it does not already exist.

    Note: this COMMITS (via `set_user_stripe_customer_id`). Never call it from
    webhook handlers, which must share a single transaction and not commit.
    """
    if user.stripe_customer_id:
        return user.stripe_customer_id

    try:
        customer = await asyncio.to_thread(
            stripe.Customer.create,
            email=user.email,
            name=user.display_name,
            metadata={"user_id": user.id},
        )
    except stripe.StripeError:
        logger.exception("Failed to create Stripe customer for user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not create billing profile. Please try again later.",
        )

    await stripe_service.set_user_stripe_customer_id(
        db=db, user_id=user.id, stripe_customer_id=customer.id
    )
    user.stripe_customer_id = customer.id
    return customer.id
