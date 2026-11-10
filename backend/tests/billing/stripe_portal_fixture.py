import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any, cast

import stripe
from stripe.params.billing_portal import (
    ConfigurationCreateParamsFeatures,
    ConfigurationUpdateParams,
    ConfigurationUpdateParamsFeatures,
    SessionCreateParamsFlowData,
)


def save(path: Path, data: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(data, stream)


def restricted_features() -> ConfigurationCreateParamsFeatures:
    return {
        "invoice_history": {"enabled": True},
        "payment_method_update": {"enabled": True},
        "subscription_cancel": {"enabled": False},
        "subscription_update": {"enabled": False},
    }


def create(client: stripe.StripeClient, args: argparse.Namespace) -> dict[str, Any]:
    assert not args.ledger.exists()
    data: dict[str, Any] = {
        "configs": [],
        "prices": [],
        "clocks": [],
        "mode": args.mode,
        "run": secrets.token_hex(8),
    }
    save(args.ledger, data)
    metadata = {"pumpkit_verification": "portal-transition", "run": data["run"]}
    product = client.v1.products.create(
        {"name": "Synthetic portal transition", "metadata": metadata}
    )
    data["product"] = product.id
    save(args.ledger, data)
    for interval, amount in [("month", 1000), ("year", 10000)]:
        price = client.v1.prices.create(
            {
                "product": product.id,
                "unit_amount": amount,
                "currency": "usd",
                "tax_behavior": "exclusive",
                "recurring": {"interval": interval},
            }
        )
        data["prices"].append(price.id)
        save(args.ledger, data)
    clock = client.v1.test_helpers.test_clocks.create(
        {"frozen_time": int(time.time()), "name": "pumpkit-430-portal-transition"}
    )
    data["clocks"].append(clock.id)
    save(args.ledger, data)
    customer = client.v1.customers.create(
        {"test_clock": clock.id, "name": "Synthetic legacy portal customer"}
    )
    data["customer"] = customer.id
    payment = client.v1.payment_methods.attach("pm_card_visa", {"customer": customer.id})
    subscription = client.v1.subscriptions.create(
        {
            "customer": customer.id,
            "items": [{"price": data["prices"][0]}],
            "default_payment_method": payment.id,
            "trial_period_days": 30,
            "billing_mode": {"type": args.mode},
        }
    ).to_dict()
    assert subscription["livemode"] is False
    data.update(subscription=subscription["id"], trial_end=subscription["trial_end"])
    save(args.ledger, data)
    if not list(client.v1.billing_portal.configurations.list({"limit": 1}).data):
        baseline = client.v1.billing_portal.configurations.create(
            {
                "features": restricted_features(),
                "login_page": {"enabled": False},
                "metadata": metadata,
            }
        )
        data["configs"].append(baseline.id)
        save(args.ledger, data)
    configuration = client.v1.billing_portal.configurations.create(
        {
            "features": {
                **restricted_features(),
                "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
                "subscription_update": {
                    "enabled": True,
                    "default_allowed_updates": ["price"],
                    "products": [{"product": product.id, "prices": data["prices"]}],
                    "proration_behavior": "create_prorations",
                    "trial_update_behavior": args.behavior,
                },
            },
            "login_page": {"enabled": True},
            "metadata": metadata,
        }
    ).to_dict()
    data["configs"].append(configuration["id"])
    data["config"] = configuration["id"]
    data["login_url"] = configuration["login_page"]["url"]
    save(args.ledger, data)
    assert configuration["is_default"] is False
    flow: SessionCreateParamsFlowData = (
        {"type": "subscription_cancel", "subscription_cancel": {"subscription": subscription["id"]}}
        if args.action == "cancel"
        else {
            "type": "subscription_update_confirm",
            "subscription_update_confirm": {
                "subscription": subscription["id"],
                "items": [
                    {
                        "id": subscription["items"]["data"][0]["id"],
                        "price": data["prices"][1],
                        "quantity": 1,
                    }
                ],
            },
        }
    )
    session = client.v1.billing_portal.sessions.create(
        {
            "configuration": configuration["id"],
            "customer": customer.id,
            "locale": "en",
            "return_url": "https://example.com/portal-verification",
            "flow_data": flow,
        }
    )
    data["session_url"] = session.url
    save(args.ledger, data)
    return {"created": True}


def execute(client: stripe.StripeClient, args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "create":
        return create(client, args)
    data = json.loads(args.ledger.read_text())
    if args.command == "restrict":
        restriction: ConfigurationUpdateParams = {
            "features": cast(ConfigurationUpdateParamsFeatures, restricted_features()),
            "login_page": {"enabled": False},
        }
        if not args.keep_active:
            restriction["active"] = False
        configuration = client.v1.billing_portal.configurations.update(data["config"], restriction)
        assert configuration.active is args.keep_active
        return {"restricted": True, "active": configuration.active}
    if args.command == "end-legacy":
        subscription = client.v1.subscriptions.cancel(
            data["subscription"], {"invoice_now": False, "prorate": False}
        )
        assert subscription.status == "canceled"
        customer = client.v1.customers.create(
            {"test_clock": data["clocks"][0], "name": "Synthetic replacement customer"}
        )
        payment = client.v1.payment_methods.attach("pm_card_visa", {"customer": customer.id})
        subscription = client.v1.subscriptions.create(
            {
                "customer": customer.id,
                "items": [{"price": data["prices"][0]}],
                "default_payment_method": payment.id,
                "trial_end": data["trial_end"] + 30 * 86400,
                "billing_mode": {"type": data["mode"]},
            }
        )
        data.update(
            replacement=subscription.id,
            replacement_customer=customer.id,
            replacement_end=subscription.trial_end,
        )
        save(args.ledger, data)
        return {"legacy_ended": True}
    if args.command == "observe":
        subscription = client.v1.subscriptions.retrieve(data["subscription"]).to_dict()
        result = {
            "status": subscription["status"],
            "price_preserved": subscription["items"]["data"][0]["price"]["id"] == data["prices"][0],
            "trial_end_preserved": subscription["trial_end"] == data["trial_end"],
            "cancellation_preserved": not subscription["cancel_at_period_end"],
            "nonzero_invoices": sum(
                invoice.amount_due != 0
                for invoice in client.v1.invoices.list(
                    {"customer": data["customer"], "limit": 100}
                ).auto_paging_iter()
            ),
        }
        if "replacement" in data:
            replacement = client.v1.subscriptions.retrieve(data["replacement"]).to_dict()
            result["replacement_preserved"] = (
                replacement["status"] == "trialing"
                and replacement["trial_end"] == data["replacement_end"]
                and replacement["items"]["data"][0]["price"]["id"] == data["prices"][0]
                and not replacement["cancel_at_period_end"]
                and not any(
                    invoice.amount_due
                    for invoice in client.v1.invoices.list(
                        {"customer": data["replacement_customer"], "limit": 100}
                    ).auto_paging_iter()
                )
            )
        return result
    failures = []
    for configuration in data["configs"]:
        try:
            existing = client.v1.billing_portal.configurations.retrieve(configuration)
            cleanup: ConfigurationUpdateParams = {
                "features": cast(ConfigurationUpdateParamsFeatures, restricted_features()),
                "login_page": {"enabled": False},
            }
            if not existing.is_default:
                cleanup["active"] = False
            client.v1.billing_portal.configurations.update(configuration, cleanup)
        except stripe.StripeError:
            failures.append("configuration")
    for clock in data["clocks"]:
        try:
            client.v1.test_helpers.test_clocks.delete(clock)
        except stripe.StripeError:
            failures.append("clock")
    for price in data["prices"]:
        try:
            client.v1.prices.update(price, {"active": False})
        except stripe.StripeError:
            failures.append("price")
    if "product" in data:
        try:
            client.v1.products.update(data["product"], {"active": False})
        except stripe.StripeError:
            failures.append("product")
    assert not failures, "Owned resource cleanup is incomplete"
    return {"cleaned_up": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["create", "restrict", "end-legacy", "observe", "cleanup"]
    )
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--mode", choices=["classic", "flexible"], default="classic")
    parser.add_argument("--behavior", choices=["continue_trial", "end_trial"], default="end_trial")
    parser.add_argument("--action", choices=["update", "cancel"], default="update")
    parser.add_argument("--keep-active", action="store_true")
    args = parser.parse_args()
    key = os.environ.get("PUMPKIT_STRIPE_TEST_KEY", "")
    assert key.startswith(("sk_test_", "rk_test_")), "Explicit Stripe test credential required"
    client = stripe.StripeClient(key, max_network_retries=0)
    assert client.v1.balance.retrieve().livemode is False
    print(json.dumps(execute(client, args)))


if __name__ == "__main__":
    try:
        main()
    except (stripe.StripeError, AssertionError, OSError, ValueError) as error:
        print(
            f"Portal verification fixture failed ({type(error).__name__}); inspect private state.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
