"""Check the rendered personal stack without printing its credentials."""

import json
import sys


def validate(config: dict) -> None:
    env = config["services"]["backend"]["environment"]
    required = {
        "STRIPE_SECRET_KEY": "sk_test_",
        "STRIPE_PUBLISHABLE_KEY": "pk_test_",
        "STRIPE_WEBHOOK_SECRET": "whsec_",
    }
    for key, prefix in required.items():
        if not str(env.get(key) or "").startswith(prefix):
            raise ValueError(f"personal mode requires sandbox {key}")
    for key in ("X_CLIENT_ID", "X_CLIENT_SECRET", "TRIAL_IDENTITY_KEYS", "BILLING_PLAN_KEYS"):
        value = env.get(key)
        if not value or (key == "BILLING_PLAN_KEYS" and not json.loads(value)):
            raise ValueError(f"personal mode requires {key}")
    for key in (
        "X_AUTHORIZE_URL",
        "X_API_URL",
        "STRIPE_API_URL",
        "GOOGLE_ISSUER",
        "GOOGLE_API_URL",
    ):
        if env.get(key):
            raise ValueError(f"personal mode refuses provider override {key}")
    if str(env.get("COUPONS_ENABLED", "false")).lower() == "true":
        for key in ("COUPON_IDENTITY_KEYS", "STRIPE_COUPON_PORTAL_CONFIGURATION_ID"):
            if not env.get(key):
                raise ValueError(f"personal coupon testing requires {key}")


if __name__ == "__main__":
    try:
        validate(json.load(sys.stdin))
    except (ValueError, KeyError, TypeError):
        # Configuration JSON contains secrets; only fixed, setting-name diagnostics leave this process.
        print(
            "dev-stack: personal configuration invalid: use sandbox Stripe keys, complete billing/X settings, no provider overrides and coupon keys/portal when enabled",
            file=sys.stderr,
        )
        sys.exit(1)
