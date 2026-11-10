# Stripe portal transition before coupon activation

This runbook supplies the outstanding-session evidence for [#430](https://github.com/pumpkit-io/pumpkit/issues/430). It supplements [ADR 0022](adr/0022-coupons-grant-cardless-free-months.md) and the [coupon activation contract](coupons.md#portal-and-activation-safeguards). It does not enable coupons, waive [#394](https://github.com/pumpkit-io/pumpkit/issues/394), or replace the billing correction in [PR #431](https://github.com/pumpkit-io/pumpkit/pull/431).

## Why changing features is insufficient

The earlier #394 browser experiment opened a price-change confirmation, then disabled subscription updates, cancellation and public login on its still-active configuration. The already-open confirmation nevertheless changed the price. Its `continue_trial` policy preserved free time and created only a zero-value invoice; that is evidence against blanket revocation, not evidence of an immediate charge.

Stripe [documents portal expiry](https://docs.stripe.com/customer-management#features) as inactivity-based: five minutes before first use, then within an hour of the most recent activity. This does not establish a fixed drain period while a customer remains active. Do not adopt an arbitrary one-hour wait, changing the app's configured portal ID, or hiding an action as proof that outstanding confirmations are harmless.

## Verified transitions

The opt-in browser harness uses stripe-python 15.6.1, API `2026-08-26.dahlia`, synthetic test-clock customers and Stripe test-mode payment methods. Six unrestricted controls first establish that equivalent synthetic price updates and cancellations really succeed. Twelve transition cases open a fully rendered confirmation before changing provider state, then submit that same page twice. Each rejection must identify the inactive configuration (400) or missing ended subscription (404/resource_missing); authentication, anti-abuse and rate-limit errors cannot pass. Provider readback must establish unchanged prices, trial ends, both cancellation fields and no nonzero invoice. Refreshed old sessions must expose no unsafe action and old public logins must be inactive.

On November 10, 2026, all 18 cases passed with retries disabled. The matrix covers classic and flexible billing, both `end_trial` and `continue_trial` price-update policies, and old cancellation confirmations. The unsafe fixture permits prorations and begins with an enabled public login; it is not the new management-only configuration. The successful `end_trial` controls intentionally produce a paid test-mode invoice. They use Stripe test cards and move no real funds; the twelve protected transition cases must create no nonzero invoice.

### Permanently deactivate non-default legacy configurations

After inventorying applicable configurations, disable their subscription updates, cancellation and public login **and set `active=false`**. The browser matrix verifies rejection of already-open update and cancellation confirmations under that combined transition. Keep those historical configurations permanently inactive; do not reopen them or give new sessions their identifiers. Create a separate validated management-only configuration for new sessions.

This is evidence for the tested flows and installed API, not a claim that changing `active` alone universally revokes every Stripe capability. An untested historical action or configuration requires its own provider-backed verification before activation.

### Clean start when the historical default cannot be deactivated

Stripe refuses to set its default portal configuration inactive. An instance can instead establish that its historical sessions have no billing target capable of consuming future coupon benefits. This procedure applies only when an existing, separately authorized clean start has already left historical customers detached and their subscriptions ended. Do not cancel subscribers, erase accounts, abandon debt or discard benefits merely to meet these conditions.

1. Keep coupons disabled until all other release and activation requirements are complete. Coordinate the final cutover so new paid signup and portal issuance cannot race the inventory.
2. Inventory every historical configuration and public login, including inactive configurations that may have issued sessions. Restrict subscription updates and cancellation and disable public login on the historical default; deactivate other historical configurations as above.
3. Read authoritative provider and local state. Historical customers must not be linked to current accounts or reused for later signup. Their subscriptions must be terminal `canceled`, not merely scheduled to cancel. Require no outstanding Checkout, invoice, pending payment/setup, schedule or other billing operation that could create or modify a commitment. Refuse activation if any outcome is unknown.
4. Recheck these conditions after restriction, then deploy the approved coupon-capable release with the explicit new management-only portal and preserved identity rings. Enable coupons only after #394 passes. New customers and subscriptions must receive new provider identities; never attach a historical customer to a recreated account.
5. Verify the running flag, restricted portal, maintenance health and application behavior. If the cutover stops before activation, retain coupons off and preserve ordinary customers' cancellation access; a default portal with cancellation disabled must not become an indefinite substitute for an enabled app's in-app cancellation controls.

The browser matrix models this boundary without cancelling any real customer: an unsafe confirmation is opened, its configuration is restricted but remains active, and the synthetic historical subscription is ended. A different synthetic customer then receives a subscription with a later protected free end. Repeated old confirmations must fail, the historical subscription must remain ended, and the replacement subscription's price, free end, cancellation choice and invoices must remain unchanged.

The supporting provider boundaries are explicit: a [portal session belongs to one customer](https://docs.stripe.com/api/customer_portal/sessions/object#portal_session_object-customer), and an [ended subscription cannot be updated](https://docs.stripe.com/billing/subscriptions/cancel), except for metadata and cancellation details. Combined with verified customer separation, these remove the old target rather than relying on an expiry estimate. Instances with live historical commitments cannot use this clean-start procedure; they need a different verified transition and must keep coupons off meanwhile.

## Notices and remaining activation checks

The authenticated Dashboard inspection recorded in PR #431 found generic trial-ending and upcoming-renewal emails off. The generic trial preview called the period a trial and described a saved card being charged; that wording is unsuitable for cardless coupon access. Do not enable those generic reminders as part of coupon activation. Enabling them separately requires appropriate wording and a verified delivery process. Test-clock events do not prove delivery.

Spec #392 does not require a new email campaign or expiry-notification subsystem. Existing in-app acceptance and billing status must still show actual free periods, independently agreed future payments and cancellation rights. This transition evidence does not provide legal approval or replace any applicable notice duty.

Activation also requires compatible plans, migrations, the persistent and backed-up coupon/trial identity rings, the explicit restricted portal, recovery/purge jobs and the final merged application validation. Preserve the default-off setting for all other instances.

## Reproduce without a running Pumpkit stack

Use a disposable worktree with the normal backend and E2E dependencies installed. Supply `PUMPKIT_STRIPE_TEST_KEY` through a private environment, then run from `e2e/`:

```sh
npm test -- --config playwright.stripe-portal.config.ts
```

The separate configuration uses a fresh visible browser, no app sign-in or global seed, no retries, and no traces/video/automatic screenshots. The normal E2E configuration excludes this file entirely. With no explicit test key, all provider cases skip. Explicit, non-assertion guards reject live-mode key prefixes before creating resources and confirm `livemode=false` through Stripe before every operation. Nine local regression cases verify key rejection, provider-mode rejection and retained cleanup state with Python optimization levels 0, 1 and 2.

Private screenshots and sanitized results stay in `pumpkit-portal-verification-*` directories under the operating system's temporary directory. Resource ledgers are mode 600 inside those private directories and are deleted after successful cleanup. Do not publish a ledger, bearer URL or credential. On cleanup failure, retain its private state and resolve the owned resources before declaring validation complete.

Cleanup deletes owned clocks and their synthetic customers, archives owned prices/products and disables owned portal configurations and public logins. If the test account originally has no portal configuration, the fixture first creates a restricted baseline default. Stripe cannot deactivate that owned default, so it remains active with subscription actions and public login disabled. Pre-existing configurations and live settings are not changed by this harness.
