"""
`SubscriptionStatus`, the statuses a Subscription can have. A leaf module, so
the billing gateway, the database models and the API schemas share one
definition without importing each other.
"""

from typing import Literal

# All possible subscription statuses according to Stripe documentation: https://stripe.com/docs/billing/subscriptions/overview#subscription-statuses
SubscriptionStatus = Literal[
    "trialing",
    "active",
    "incomplete",
    "incomplete_expired",
    "past_due",
    "canceled",
    "unpaid",
    "paused",
]
