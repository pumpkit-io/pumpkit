# Dev stack

- Entry point: `scripts/dev-stack`
- Strategy: B
- Project: `pumpkit`
- Health URL: `/api/v1/health`
- e2e: `cd e2e && npm test`
- Cap: 10
- Portless: 0.15.12
- Emulate: 0.13.0
- Proxy: HTTP on 1355

## Emulators

Emulator state resets to its config whenever `up` starts an Emulator, so on the first `up` after `down`. `scripts/dev-stack` adds `compose.emulators.yml`, which hands the backend the variables `up` sets over `.env`'s.

- Google sign-in: route `google.emulate.pumpkit`; `up` sets `GOOGLE_ISSUER` (browser-facing, also the token issuer) and `GOOGLE_API_URL` (server-to-server), with throwaway `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`; no webhooks; `GET /o/oauth2/v2/auth` lists the seeded users; `emulate.config.ts` seeds the user `test@example.com`, beside emulate's own `testuser@gmail.com`.
- X: custom service `pumpkit-x.emulate.pumpkit`. `up` sets paired `X_AUTHORIZE_URL` (browser-facing) and `X_API_URL` (server-to-server), with throwaway X client credentials. Authorization validates the registered local callback, state and S256 PKCE; codes and refresh tokens are single-use. Seeded accounts include Ada, Grace, one account without confirmed email, and the browser fixtures. `GET /_pumpkit/events` reports only operation kinds and fake user IDs; `/_emulate` is its Inspector. No webhooks. Unsupported publishing/media calls return a local refusal rather than reaching X.
- Stripe: a custom Emulator, `emulators/stripe.ts`, serving only the calls `backend/src/pumpkit/billing/gateway.py` makes. emulate refuses a custom service named after its built-in `stripe`, so the route is `pumpkit-stripe.emulate.pumpkit`.
  - `up` sets `STRIPE_API_URL`, `STRIPE_WEBHOOK_URL` and `STRIPE_WEBHOOK_SECRET`, with throwaway `STRIPE_SECRET_KEY` and `STRIPE_PUBLISHABLE_KEY`, and `BILLING_PLAN_KEYS` and `BILLING_TOP_UP_KEY` set to the seeded lookup keys.
  - It delivers signed webhooks to `http://backend:8000/api/v1/stripe/webhook`. `GET /_pumpkit/webhook-deliveries` lists each delivery, its customer and the status the backend answered; `/_emulate` is its Inspector.
  - `emulate.config.ts` seeds the Plans `pumpkit_pro_monthly` and `pumpkit_pro_yearly`, the Top-up `pumpkit_top_up`, and the customers and Subscriptions that `e2e/seed/seed_user.py` and `onboarding_user.py` link their Users to (`cus_e2e` with `sub_e2e`).
  - Its Checkout and billing portal are pages of its own: Pay completes a Checkout and Cancel sets a Subscription's `cancel_at`, each sending its webhooks before the browser returns to Pumpkit. Every payment succeeds.
  - It has no clock: a Trial stays a Trial and a `cancel_at` never cancels until something calls the API.
  - When `gateway.py` starts a new Stripe call, add the route to `emulators/stripe.ts`, or the dev stack answers it with a 404.

## Safe mode

- `TRIAL_IDENTITY_KEYS` is a committed throwaway ring supplied only by `compose.emulators.yml`, so local X-account eligibility checks never use an Instance's real keys.

- `PUBLISHER_ENABLED=false`: the publisher process runs but publishes nothing. X API overrides also cover direct Post now and media requests, so those cannot fall back to real X.
- `SMTP_HOST=` and `EMAIL_FROM=`: Magic links are logged instead of emailed. Blanking only one leaves SMTP partly configured, and the backend refuses to start. emulate covers Resend, not SMTP, so mail is a custom-Emulator candidate.
- `POSTHOG_ENABLED=false`: the backend sends no analytics events. PostHog is a custom-Emulator candidate.
- twitterapi.io, the LLM endpoint and Jev (TypeSafe's classifier) only read or generate, so nothing is switched off; each is a custom-Emulator candidate.

## E2E data

`make e2e` starts this contract when no `E2E_BASE_URL` is supplied; CI installs the pinned Portless version first. Browser seeds use deterministic X IDs and are CLI-only fixtures that refuse production or a missing local X provider. General backend authorization fixtures use the existing session service directly; focused tests retain the inactive-flow helpers they exercise.

Before X-only activation, the normal app deliberately keeps the prepared X start/completion routes unmounted. The contract also starts the explicit local-only `tests.staged_x_app:create_app` browser fixture, at `scripts/dev-stack staged-x-url`. It uses the real prepared routes and official provider adapter against the stand-in. Its factory refuses production and missing X overrides; it is never imported by `pumpkit.main`. The normal Dev URL remains unchanged, and its prepared routes still answer 404 until cutover. The fixture's callback removes query credentials before rendering and never stores them in analytics or logs.

Run only the protocol smoke with `E2E_BASE_URL=$(scripts/dev-stack url) npm --prefix e2e test -- tests/x-sign-in.spec.ts`. It covers fresh/returning sign-in, confirmed-email refusal and cancellation without live X credentials. The full suite remains the final stack check. When reusing data created by older email-based browser seeds, first destroy only this worktree's dev stack and start it again.

Use `e2e/backend.ts` to run scripts from `e2e/seed/` inside this worktree's backend container. They seed local Users, Subscriptions and usage without calling providers. The usage smoke tests need the dummy billing configuration and caps in [CONTRIBUTING.md](../../CONTRIBUTING.md#make-targets); they stub the Stripe-backed catalog response and cancel purchase dialogs before payment.

## Browsers

Chrome, Firefox, Edge, `curl` and Node's `fetch` resolve `*.localhost` on their own. Safari may not: run `portless hosts sync` once when a Dev URL doesn't resolve there.

The staged assembly fetches only the exact local provider avatar URL with a test-owned photo adapter. The production photo adapter keeps its HTTPS-only rule.
