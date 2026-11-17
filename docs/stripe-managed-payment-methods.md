# Managed Payments subscription card verification

This is the provider proof for [#557](https://github.com/pumpkit-io/pumpkit/issues/557), under [ADR 0033](adr/0033-changing-seller-preserves-billing-commitments.md). It chooses the hosted contract for #563. It does not activate Managed Payments, prove Link's other subscription actions, or establish production notice coverage.

The installed integration uses stripe-python 15.6.1 and API `2026-08-26.dahlia`.

## Two different card operations

The restricted Stripe portal shows two separate operations:

- **Payment methods → Add payment method** saves a card and makes it the Customer default. It leaves the Managed Payments Subscription's payment method unchanged. This is the negative control, not a successful Subscription card replacement.
- **Current subscription → Update payment method** opens a Subscription-specific selection. Its pencil button is available for ordinary and deferred Subscriptions. A failed-payment Subscription instead shows an **Update payment method** link and a **Subscribe and pay** confirmation to settle the failed payment. The selection can choose an existing card or add a new one and authorizes Link to charge that Subscription.

The tested configuration enables payment-method updates and invoice history, while subscription updates, cancellation and public login are disabled. Read-only production SSH and Stripe API inspection on November 16, 2026 confirmed the configured active live portal has those same feature flags. That comparison establishes configuration equivalence; the payment results below are from test mode. No direct API assignment to `subscription.default_payment_method` is used. The verified destination is the existing restricted portal session; the Subscription action inside it matters. Sending a customer straight to the generic `payment_method_update` flow would select the wrong contract.

Stripe's [Managed Payments documentation](https://docs.stripe.com/payments/managed-payments/how-it-works#manage-orders) distinguishes hosted Subscription updates from prohibited direct payment-method assignment. Its [portal deep-link documentation](https://docs.stripe.com/customer-management/portal-deep-links) says the generic flow sets `customer.invoice_settings.default_payment_method`.

## Reproduce

Install the backend and E2E dependencies and Chromium. Supply `PUMPKIT_STRIPE_TEST_KEY` privately with a sandbox `sk_test_` or `rk_test_` credential. Do not put it on the command line, in a committed file or in a shared log. From `backend/`:

```sh
uv run --extra dev pytest tests/billing/test_stripe_managed_payments_live.py -k replaces -q
```

Set `PUMPKIT_STRIPE_RESULTS` to a file in a private directory to retain the sanitized outcome records. The six cases use synthetic customers, products, test cards and clocks. They run without a Pumpkit stack. The card-management browser is visible; a graphical display, or an explicitly configured virtual display on Linux, is required. The normal suite skips these provider cases without an explicit credential.

The provider fixture rejects live credentials before making API calls and verifies `livemode=false`. The browser receives its URL through a mode-600 ledger, accepts only Stripe's test-session URL format, and refuses malformed input without echoing it. Checkout URLs pass through standard input rather than process arguments. Browser traces and recordings are not enabled. Failure screenshots and page text stay beside the private ledger in pytest's temporary directory; keep that directory protected and never upload those files as public CI artifacts.

Cleanup deletes owned clocks and their customers/Subscriptions, deactivates owned non-default portal configurations and archives the owned products/prices. Stripe cannot deactivate a default portal configuration: if this is the first one in an unconfigured sandbox, it remains active with subscription actions and login disabled. A failed card-fixture cleanup fails the case. Investigate any cleanup warning from the shared catalog fixture before declaring a run complete. The test does not alter an existing portal configuration, catalog price or production setting.

## Verified result on November 16, 2026

The complete matrix passed: **6 passed, 5 deselected in 331.49 seconds**, with no provider cleanup warning. A separate run after ledger-permission and cleanup-failure hardening passed the new-card case again: **1 passed, 10 deselected in 62.21 seconds**. Seven credential/URL/privacy refusal cases passed in the ordinary E2E safety check, alongside its existing personal-instance refusal case. A deliberately supplied live-key prefix was refused before any provider call.

The [committed sanitized outcome record](stripe-managed-payment-method-results.json) contains the `PUMPKIT_STRIPE_RESULTS` observations from that complete matrix, with its run metadata. It contains no credentials, bearer URLs, card information, customer contact data or provider object identifiers. Each of the five paying cases produced a successful €19.00 replacement-card charge; cancellation produced none. The paid-up negative control also produced a subsequent original-card charge after only the Customer default changed. All temporary fixtures were cleaned up; the separate manual exploration fixtures were deleted or archived too.

## Provider observations

The evidence records Customer default, Subscription method and subsequent charges separately. Every successful card update must preserve trial end, billing anchor, period end, price interval and both cancellation fields. A URL, redirect or new Customer default does not pass.

- Trial: choose an existing replacement card, then reach the agreed first-payment date and require its €19.00 payment to use that card.
- Trial with a new card: enter a new card within the Subscription action and prove its first payment.
- Paid up: show that a later payment still uses the original card after the generic Customer-default operation; then use the Subscription action and prove the next renewal uses the replacement.
- Past due: begin with a test card whose later charge fails, replace it through the hosted recovery action, settle the invoice and verify the Subscription uses the replacement.
- Cancelled renewal: replace the card while preserving cancellation; the Subscription must end on the agreed date with no renewal charge.
- Free access deferral: preserve the deferred payment date and charge the replacement only after that date.

This harness proves provider billing behavior. It does not manufacture local Coupon benefits or prove Pumpkit's Allowance calculation, acceptance records or webhook delivery. The existing application suites and later activation gates cover those separately. Do not use this evidence to waive #558's Link-action verification or the actual paid live verification.

## Application journey retained for #563

The supported app destination remains `POST /billing/portal`, using the explicit restricted configuration when Coupons or Free access require it. In the hosted portal, use **Current subscription → Update payment method**. The generic Customer-default action is insufficient, as the negative control above demonstrates. The [customer-action investigation](stripe-customer-actions.md) also retains an old seller-mode Subscription after the Instance enables Managed Payments. Neither case needs a new mode projection or Link route in Pumpkit.

Settings keeps its existing Manage billing (or Manage subscription with Coupons disabled) and Fix payment actions, cancellation and frequency controls, and pending-operation guards. While requesting the destination, all billing entry points share one in-flight request and show **Opening billing…** disabled. Failure leaves confirmed billing data visible with an inline error and a retry. Once the destination request settles, the opening state clears, including when navigation is cancelled. A normal return mounts Settings and reloads billing; a browser-cache restoration refreshes it through `pageshow.persisted`. Neither return claims a card update succeeded.

This application change reuses the real test-mode replacement/subsequent-payment results above and the old-mode evidence in the customer-action investigation; it makes no new real-provider payment claim. Authenticated Link and guest-receipt actions, older Link capabilities, remaining independent provider-action races and the authorized paid live verification remain mandatory final #499 gates before general purchases reopen.
