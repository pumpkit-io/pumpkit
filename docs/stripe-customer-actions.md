# Managed Payments customer-action verification

This is the provider and application evidence for [#558](https://github.com/pumpkit-io/pumpkit/issues/558), under [ADR 0022](adr/0022-coupons-grant-cardless-free-months.md) and [ADR 0033](adr/0033-changing-seller-preserves-billing-commitments.md). It builds on the [subscription card proof](stripe-managed-payment-methods.md) and [historical portal-transition evidence](stripe-portal-transition.md). It changes no application behavior or production setting.

## Execution status

The intermediate sandbox scope of [#558](https://github.com/pumpkit-io/pumpkit/issues/558) is complete. On November 17, 2026, 19 sandbox portal/application scenarios were verified: six completed monthly cases, 12 remaining cases after correcting a seller-mode browser completion signal, and one separate uncertain-Coupon case. The 25-case portal-transition suite passed in 10.5 minutes. The maintainer approved postponing the blocking Link and independent provider-race verification to final activation task [#499](https://github.com/pumpkit-io/pumpkit/issues/499), allowing the remaining implementation work under #556 to proceed. Link order management remains unverified. General purchases must stay closed until the deferred verification passes; this evidence authorizes no production purchase or provider setting change.

The [sanitized outcome record](stripe-customer-action-results.json) preserves the split-run provenance, anonymous provider dates/amounts, application Allowance limits and transition outcomes. The first run stopped at a browser wait after its six completed cases; it is not reported as a successful consolidated 18-case run. The subsequent 12-case run passed in 801.91 seconds, and the separate Coupon case passed in 87.22 seconds.

The installed integration is stripe-python 15.6.1, API `2026-08-26.dahlia`. Managed Payments subscriptions in the new transition cases start through hosted test-mode Checkout, using the installed flexible billing mode. Ordinary classic/flexible transition cases remain in the same suite.

## Link is a separate provider surface

Stripe's [Managed Payments testing instructions](https://docs.stripe.com/payments/managed-payments/update-checkout#link) state: “Test purchases won’t appear in the Link app.” They document `000000` for authenticating a Link account during sandbox Checkout, but direct order-management testing to a Link account created during a live-mode Checkout Session. That is not evidence that the app's order controls work in a sandbox, and it does not explicitly require a paid result rather than a live Trial.

A synthetic paid sandbox purchase was completed through Pumpkit's gateway and hosted Checkout on November 17, 2026. Its invoice was paid and its receipt offered **Manage subscription**, pointing to `app.link.com/view`. The guest landing named the sandbox purchase and requested Link sign-up. An interactive hCaptcha challenge kept its fixed synthetic email and Log in controls disabled. No challenge was solved or bypassed, no OTP was reached, and no post-authentication order action was observed. The owned customer, subscription, clock, catalog and exploratory portal configuration were cleaned up.

This establishes the receipt-originated route and the unattended authentication boundary. It does not prove that receipt-originated sandbox order tools are absent after authentication. The direct Link app and guest receipt route must remain distinct in the evidence.

Restricted Stripe portal settings do not establish restrictions on Link. The final #499 Link gate remains open for account and guest journeys, card replacement, cancellation, price changes, old receipts/links, and effects on paid/free coverage, cancellation intent and agreed payment dates. Checkout login or a success redirect cannot close that gate.

## Restricted portal and application seam

The opt-in application matrix uses the authenticated billing HTTP API with a real Stripe gateway and synthetic sandbox subscriptions. Its explicit portal configuration enables payment-method updates and invoice history, while subscription updates, cancellation and public login are disabled. The card action is opened through `POST /billing/portal`, rather than constructing a different app destination.

The cases cover monthly and annual billing with paid-up, introductory Trial, current and queued Free access, cancelled renewal and past-due states. Free access is redeemed through Pumpkit's HTTP Coupon flow. Current and queued Free access are also tested with renewal cancelled. An existing seller-mode subscription is exercised while the Instance setting selects Managed Payments for future purchases; its provider mode must stay unchanged.

For each case, the browser inspects the new session's card control and absence of cancellation/price-change controls, then replaces the subscription's card through the hosted action. Absence of a control is recorded as absence, not provider rejection or revocation of an older session. Provider dates, cancellation fields and nonzero invoices are compared before and after. Past-due recovery may settle its already-agreed invoice; it must not move dates or produce a duplicate payment.

The subsequent payment must use the replacement method at the agreed date and amount (€19 monthly or €190 annual in the owned catalog). Cancelled renewal must produce no replacement-card charge. `GET /billing/me` and `GET /usage` establish retained access, Free access and Allowance before/after the card action and at the later payment/cancellation date.

A test-signed subscription nudge deliberately carries a stale cancelled status. Pumpkit must read current real Stripe state rather than apply that payload. Each nudge is submitted twice with the same event ID, so the readback also covers replay handling. These are locally delivered, test-signed HTTP requests; they do not claim actual Stripe-to-Pumpkit webhook delivery.

## Previously issued portal confirmations

The transition matrix keeps its unrestricted controls, then opens update/cancellation confirmations before changing the provider configuration. The added Managed Payments cases exercise both `end_trial` and `continue_trial` price-update policies and cancellation.

A separate restriction-only control disables subscription actions and login while leaving the old configuration active. On this installed Managed Payments path, submitting the old price confirmation returned HTTP 400 with `invalid_request_error`: the subscription update feature was disabled. Two submissions must receive that specific feature refusal, while dates, price, cancellation and invoices stay unchanged. The unrestricted control establishes that the equivalent action succeeds before restriction. This narrow result does not replace the historical ordinary-subscription evidence that feature restriction alone was insufficient.

The stronger transition deactivates the owned non-default configuration as well as restricting its features, then submits the old confirmation twice. Only the expected inactive-configuration provider refusal passes; authentication, anti-abuse and rate-limit responses do not count. Provider readback must retain price, trial end and cancellation, with no nonzero invoice. The old public login must be inactive.

This tests the installed Managed Payments path. It does not claim that every Link capability is revoked, that a default configuration can be deactivated, or that an arbitrary expiry wait is sufficient. Existing [default-configuration and historical-customer safeguards](stripe-portal-transition.md#clean-start-when-the-historical-default-cannot-be-deactivated) remain separate.

## Pending application operations

A real-Stripe Coupon case persists an uncertain operation after its provider deferral succeeds but the gateway loses the response. An already-issued restricted portal remains usable for card replacement while issuing a new portal returns 409. A test-signed current-state nudge recovers that operation once: one deferral call, one free month, unchanged paid Allowance and the agreed later replacement-card payment. Repeated nudge/recovery reads must not duplicate benefits.

The existing deterministic HTTP/recovery regressions cover pending Coupon dispatch, paid signup and Plan-change operations, cancelled Coupon coverage and repeated recovery. On November 17, 2026, the four relevant test modules passed 131 tests. Their gateway is controlled; they prove application guards and reconciliation for those supplied provider states. They do not prove what Link exposes or which writes Link can race through an independently issued capability.

## Deferred final activation verification

Task [#499](https://github.com/pumpkit-io/pumpkit/issues/499) must complete the following matrix after compatible safeguards are installed and before general purchases reopen:

- Authenticated Link account and guest-receipt journeys: card replacement, cancellation, available price changes and older Link links or capabilities.
- Monthly and annual subscriptions in Trial, paid-up, past-due, cancelled renewal and current/queued Free access states, including effects on paid/free coverage, cancellation intent and agreed payment dates.
- Independent provider-action races with pending Coupon, paid-signup and Plan-change operations where applicable, beyond the real-provider uncertain Coupon case and controlled-gateway regressions recorded here.

Each action needs actual provider payment/date readback and Pumpkit access/Allowance after current-state synchronization, classified as prevented, safely reconciled or blocking. Sandbox limitations and the unattended authentication barrier remain unresolved evidence boundaries. A supported provider route or a separately authorized bounded live plan must supply the missing proof. The ordering decision selects no verification identity and authorizes no spending or irreversible provider choice. Any unverified or incompatible outcome keeps purchases closed and requires a reviewed correction without weakening ADR 0022's commitments.

## Reproduce

Supply a sandbox `PUMPKIT_STRIPE_TEST_KEY` privately. Do not put credentials, receipt links, portal URLs or resource ledgers in command arguments, public logs or artifacts. Dependencies and Chromium must be installed; the provider browsers require a display or an explicitly configured virtual display. From the repository root:

```sh
uv run --project backend --extra dev pytest backend/tests/billing/test_stripe_customer_actions_live.py -q
npm --prefix e2e test -- --config playwright.stripe-portal.config.ts
```

Set `PUMPKIT_STRIPE_RESULTS` to a protected file to retain the application matrix's sanitized observations. The ordinary suite skips provider cases without an explicit credential. The transition CLI's live-key and provider-mode guards are verified with Python optimization levels 0, 1 and 2, before resource creation. The application matrix separately reuses #557's fixture, which requires a test-key prefix and test-mode balance before creating its catalog; it has not been exercised under optimized Python. A test clock and its customers are deleted after each application case; owned prices/products are archived and non-default portal configurations deactivated. If the hosted browser fails before completion, cleanup first expires its ledger-owned open Checkout and reads back a closed state before deleting the clock. A completed Checkout is left complete; an expiration/completion race is reconciled. Unknown or failed expiration stops cleanup and retains the ledger. Nineteen controlled fixture guards passed, and a real-sandbox injected browser failure was recovered to an expired Checkout and removed clock. Cleanup failure is not success.

Browser screenshots and page text, receipt links and exploration ledgers remain in private temporary directories. The committed outcome record contains only anonymous case names, dates, amounts and assertion outcomes. The portal-transition result files contain no bearer URLs or customer identity; keep their private directory protected and publish only reviewed sanitized records.

## Cleanup boundary

Known, ledger-bound fixtures from the completed proof were cleaned up. A read-only sandbox inventory observed two open Sessions that could not be bound to the available local ledgers. They were left untouched; earlier failed-run ledgers had already been removed by the previous cleanup path. This does not assert that those Sessions belong to this work, or claim global historical cleanup. The protected inventory remains outside the repository.
