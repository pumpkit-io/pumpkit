# Browser tests

Run the normal default-off suite with `E2E_BASE_URL=<Dev URL> npm test` from this directory. Use `scripts/dev-stack` from the repository root to manage its stack.

## Coupon journeys

Use a disposable linked worktree with its own `.env` and stack. From its root:

```sh
node e2e/coupons-env.mjs prepare
scripts/dev-stack up
```

The preparation script saves the worktree's previous `.env` privately in `.sdlc/dev-stack/`, enables coupons, and supplies a throwaway identity key and the local Emulator's management-only portal configuration. `scripts/dev-stack` supplies local Stripe and Google Emulators and development credentials; never run these journeys against Stripe itself.

Run the complete suite, including all Coupon journeys, from `e2e/`:

```sh
E2E_COUPONS=1 E2E_BASE_URL=<Dev URL> npm test
```

For focused authoring, append `-- tests/coupons.spec.ts`. Opting in fails if the running backend does not enable coupons or does not use the local Stripe Emulator configuration; it never silently skips the journeys. Without `E2E_COUPONS=1`, only this optional Coupon suite is skipped and the existing default-off suite runs as before.

The seed helper creates a different account and recipient-bound code for every journey. It issues coupons through the privileged billing service and buys subscriber fixtures through the local Emulator. The browser confirms benefits, recovery, future payment consent and access gates through the app and authenticated API. Only access expiry and finished onboarding are advanced through seed data. Browser traces are disabled for these journeys so redemption codes and session tokens do not enter trace artifacts.

Afterward, from the root:

```sh
scripts/dev-stack destroy
node e2e/coupons-env.mjs restore
```
