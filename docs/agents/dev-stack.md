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
- Stripe: a custom Emulator, `emulators/stripe.ts`, serving only the calls `backend/src/pumpkit/billing/gateway.py` makes. emulate refuses a custom service named after its built-in `stripe`, so the route is `pumpkit-stripe.emulate.pumpkit`.
  - `up` sets `STRIPE_API_URL`, `STRIPE_WEBHOOK_URL` and `STRIPE_WEBHOOK_SECRET`, with throwaway `STRIPE_SECRET_KEY` and `STRIPE_PUBLISHABLE_KEY`, and `BILLING_PLAN_KEYS` and `BILLING_TOP_UP_KEY` set to the seeded lookup keys.
  - It delivers signed webhooks to `http://backend:8000/api/v1/stripe/webhook`. `GET /_pumpkit/webhook-deliveries` lists each delivery, its customer and the status the backend answered; `/_emulate` is its Inspector.
  - `emulate.config.ts` seeds the Plans `pumpkit_pro_monthly` and `pumpkit_pro_yearly`, the Top-up `pumpkit_top_up`, and the customers and Subscriptions that `e2e/seed/seed_user.py` and `onboarding_user.py` link their Users to (`cus_e2e` with `sub_e2e`).
  - Its Checkout and billing portal are pages of its own: Pay completes a Checkout and Cancel sets a Subscription's `cancel_at`, each sending its webhooks before the browser returns to Pumpkit. Every payment succeeds.
  - It has no clock: a Trial stays a Trial and a `cancel_at` never cancels until something calls the API.
  - When `gateway.py` starts a new Stripe call, add the route to `emulators/stripe.ts`, or the dev stack answers it with a 404.

## Safe mode

- `PUBLISHER_ENABLED=false`: the publisher process runs but publishes nothing to X. X has no Emulator in emulate 0.13.0, so it is a custom-Emulator candidate.
- `SMTP_HOST=` and `EMAIL_FROM=`: Magic links are logged instead of emailed. Blanking only one leaves SMTP partly configured, and the backend refuses to start. emulate covers Resend, not SMTP, so mail is a custom-Emulator candidate.
- `POSTHOG_ENABLED=false`: the backend sends no analytics events. PostHog is a custom-Emulator candidate.
- twitterapi.io, the LLM endpoint and Jev (TypeSafe's classifier) only read or generate, so nothing is switched off; each is a custom-Emulator candidate.

## E2E data

Use `e2e/backend.ts` to run scripts from `e2e/seed/` inside this worktree's backend container. They seed local Users, Subscriptions and usage without calling providers. The usage smoke tests need the dummy billing configuration and caps in [CONTRIBUTING.md](../../CONTRIBUTING.md#make-targets); they stub the Stripe-backed catalog response and cancel purchase dialogs before payment.

## Browsers

Chrome, Firefox, Edge, `curl` and Node's `fetch` resolve `*.localhost` on their own. Safari may not: run `portless hosts sync` once when a Dev URL doesn't resolve there.
