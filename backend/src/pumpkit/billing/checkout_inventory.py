from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.billing.gateway import HostedCheckout, checkout_parameters
from pumpkit.billing.models import CheckoutDispatch, PaidSignup, Subscription, TopUp
from pumpkit.core.config import settings


@dataclass(frozen=True)
class Relationships:
    customers: dict[str, set[str]]
    sessions: dict[str, str]
    paid_signups: dict[str, str]
    users: set[str]


async def relationships(db: AsyncSession) -> Relationships:
    customers: dict[str, set[str]] = {}
    sessions: dict[str, str] = {}
    signups: dict[str, str] = {}
    user_ids = set()
    for user in await db.scalars(select(User)):
        user_ids.add(user.id)
        if user.stripe_customer_id:
            customers.setdefault(user.stripe_customer_id, set()).add(user.id)
    for subscription in await db.scalars(select(Subscription)):
        customers.setdefault(subscription.stripe_customer_id, set()).add(subscription.user_id)
    for operation in await db.scalars(select(PaidSignup)):
        if operation.customer_id:
            customers.setdefault(operation.customer_id, set()).add(operation.user_id)
        if operation.session_id:
            sessions[operation.session_id] = operation.user_id
            signups[operation.session_id] = operation.id
    for purchase in await db.scalars(select(TopUp)):
        sessions[purchase.stripe_checkout_session_id] = purchase.user_id
    return Relationships(customers, sessions, signups, user_ids)


def ownership(
    session: HostedCheckout,
    *,
    instance_id: Optional[str],
    dispatches: list[CheckoutDispatch],
    relationships: Relationships,
    livemode: Optional[bool] = None,
) -> tuple[str, Optional[str]]:
    if livemode is not None and session.livemode != livemode:
        return "unknown", None
    marker = session.metadata.get("pumpkit_dispatch")
    claims = [d for d in dispatches if d.id == marker or d.session_id == session.id]
    if claims:
        if len(claims) != 1:
            return "unknown", None
        dispatch = claims[0]
        params = dispatch.parameters
        if not (
            dispatch.session_id == session.id
            and params["metadata"].get("pumpkit_instance") == instance_id
            and session.metadata == params["metadata"]
            and session.customer_id == params["customer"]
            and session.user_id == dispatch.user_id == params["client_reference_id"]
            and session.mode == params["mode"]
            and session.success_url == params["success_url"]
            and session.cancel_url == params["cancel_url"]
            and session.managed_payments == params["managed_payments"]["enabled"]
        ):
            return "unknown", None
        return "owned", dispatch.user_id
    if marker or session.metadata.get("pumpkit_instance"):
        # An unjoined marker cannot establish another Instance's ownership.
        return "unknown", None
    users = relationships.customers.get(session.customer_id or "", set())
    exact_user = relationships.sessions.get(session.id)
    if exact_user and (session.user_id != exact_user or (users and users != {exact_user})):
        return "unknown", None
    if session.user_id and (
        (session.user_id in users and len(users) == 1) or exact_user == session.user_id
    ):
        kind = (
            "top_up"
            if session.metadata.get("pumpkit_purchase") == "top_up"
            else (
                "arranged_paid_signup"
                if session.metadata.get("pumpkit_paid_signup")
                else "subscription"
            )
        )
        if session.metadata.get("pumpkit_purchase") not in {None, "top_up"}:
            return "unknown", None
        expected = checkout_parameters(
            kind="top_up" if kind == "top_up" else "subscription",
            customer_id=session.customer_id or "",
            user_id=session.user_id,
            price_id="unused",
        )
        if kind == "arranged_paid_signup":
            # An exact retained signup Session is required for historical signup attribution.
            if exact_user != session.user_id or session.metadata.get(
                "pumpkit_paid_signup"
            ) != relationships.paid_signups.get(session.id):
                return "unknown", None
            expected["success_url"] = expected["cancel_url"] = settings.billing_page_url()
            expected["metadata"] = {"pumpkit_paid_signup": relationships.paid_signups[session.id]}
        if (
            session.mode == expected["mode"]
            and session.success_url == expected["success_url"]
            and session.cancel_url == expected["cancel_url"]
            and session.metadata == expected.get("metadata", {})
        ):
            return "owned", session.user_id
        return "unknown", None
    origin = urlsplit(
        checkout_parameters(kind="subscription", customer_id="", user_id="", price_id="")[
            "success_url"
        ]
    )
    origins = [urlsplit(url) for url in (session.success_url, session.cancel_url)]
    if (
        not users
        and not exact_user
        and session.user_id not in relationships.users
        and all(
            o.scheme in {"https", "http"}
            and o.netloc
            and (o.scheme, o.netloc) != (origin.scheme, origin.netloc)
            for o in origins
        )
    ):
        return "foreign", None
    return "unknown", None
