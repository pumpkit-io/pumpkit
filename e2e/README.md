# Browser tests

Run the normal default-off suite with `E2E_BASE_URL=<Dev URL> npm test` from this directory. Use `scripts/dev-stack` from the repository root to manage its stack.

## Coupon journeys

Use a disposable linked worktree with its own `.env` and stack. From its root:

```sh
node e2e/coupons-env.mjs prepare
scripts/dev-stack up
```

The preparation script saves the worktree's previous `.env` privately in `.sdlc/coupons-env-backup`, outside the stack data removed by `destroy`, enables coupons, and supplies a throwaway identity key and the local Emulator's management-only portal configuration. It also sets dummy operator details (`Pumpkit E2E`, `support@e2e-user.dev`) so the current Terms appear and every journey exercises acceptance: two boxes for a coupon, three for a future paid subscription. The dev stack keeps SMTP off; no email is sent. `scripts/dev-stack` supplies local Stripe and Google Emulators and development credentials; never run these journeys against Stripe itself.

Run the complete suite, including all coupon journeys, from `e2e/`:

```sh
E2E_COUPONS=1 E2E_BASE_URL=<Dev URL> npm test
```

For focused authoring, append `-- tests/coupons.spec.ts`. Opting in fails if the running backend does not enable coupons or does not use the local Stripe Emulator configuration; it never silently skips the journeys. Without `E2E_COUPONS=1`, only this optional coupon suite is skipped and the existing default-off suite runs as before.

The seed helper creates a different account and recipient-bound code for every journey. It issues coupons through the privileged billing service and buys subscriber fixtures through the local Emulator. The browser confirms benefits, recovery, future payment consent and access gates through the app and authenticated API. Only access expiry and finished onboarding are advanced through seed data. The suite captures the real enabled catalog once per worker and serves that unchanged response for repeated React loads, keeping those reads below the shared public catalog rate limit. All acceptance and billing operations still reach the backend and Emulator. Browser traces are disabled for these journeys so redemption codes and session tokens do not enter trace artifacts.

Afterward, from the root:

```sh
scripts/dev-stack destroy
node e2e/coupons-env.mjs restore
```

## Real Stripe portal transition verification

The separate, opt-in provider harness in [the portal transition runbook](../docs/stripe-portal-transition.md) exercises only synthetic Stripe test-mode sessions. It does not start a Pumpkit stack or use the Emulator coupon journeys above. With an explicit `PUMPKIT_STRIPE_TEST_KEY` supplied privately, run:

```sh
npm test -- --config playwright.stripe-portal.config.ts
```

Live keys are refused, and the normal E2E configuration excludes these tests. The runbook defines the two tested transitions, credential handling, private artifacts, resource cleanup and the activation conditions; passing this harness alone does not enable production coupons.

## Managed Payments verification

`stripe-checkout.mjs` completes a Stripe test-mode hosted Checkout with Stripe's Visa test card in headless Chromium. Only the opt-in backend test `backend/tests/billing/test_stripe_managed_payments_live.py` uses it, to start Subscriptions Stripe records as Managed Payments ones and check every Subscription update Pumpkit makes on them. After `npm ci` and `npx playwright install chromium` here, run it from `backend/`:

```sh
PUMPKIT_STRIPE_TEST_KEY=<sk_test_ key> uv run --extra dev pytest tests/billing/test_stripe_managed_payments_live.py
```

It creates its own products with an eligible tax code, refuses a live key and deletes or archives what it creates. `PUMPKIT_STRIPE_RESULTS=<file>` also writes what Stripe answered to each call and the Subscription's state after it.
