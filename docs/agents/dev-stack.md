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

- Retained inactive Google adapter tests: route `google.emulate.pumpkit`; `up` sets `GOOGLE_ISSUER` (browser-facing, also the token issuer) and `GOOGLE_API_URL` (server-to-server), with throwaway `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`; no webhooks; `GET /o/oauth2/v2/auth` lists the seeded users; `emulate.config.ts` seeds the user `test@example.com`, beside emulate's own `testuser@gmail.com`.
- X: custom service `pumpkit-x.emulate.pumpkit`. `up` sets paired `X_AUTHORIZE_URL` (browser-facing) and `X_API_URL` (server-to-server), with throwaway X client credentials. Authorization validates the registered local callback, state and S256 PKCE; codes and refresh tokens are single-use. Seeded accounts include Ada, Grace, one account without confirmed email, and the browser fixtures. `GET /_pumpkit/events` reports only operation kinds and fake user IDs; `/_emulate` is its Inspector. No webhooks. Unsupported publishing/media calls return a local refusal rather than reaching X.
- Stripe: a custom Emulator, `emulators/stripe.ts`, serving only the calls `backend/src/pumpkit/billing/gateway.py` makes. emulate refuses a custom service named after its built-in `stripe`, so the route is `pumpkit-stripe.emulate.pumpkit`.
  - `up` sets `STRIPE_API_URL`, `STRIPE_WEBHOOK_URL` and `STRIPE_WEBHOOK_SECRET`, with throwaway `STRIPE_SECRET_KEY` and `STRIPE_PUBLISHABLE_KEY`, and `BILLING_PLAN_KEYS` and `BILLING_TOP_UP_KEY` set to the seeded lookup keys.
  - It delivers signed webhooks to `http://backend:8000/api/v1/stripe/webhook`. `GET /_pumpkit/webhook-deliveries` lists each delivery, its customer and the status the backend answered; `/_emulate` is its Inspector.
  - `emulate.config.ts` seeds the Plans `pumpkit_pro_monthly` and `pumpkit_pro_yearly`, the Top-up `pumpkit_top_up`, and the customers and Subscriptions that `e2e/seed/seed_user.py` and `onboarding_user.py` link their Users to (`cus_e2e` with `sub_e2e`).
  - Its Checkout and billing portal are pages of its own: Pay completes a Checkout and Cancel sets a Subscription's `cancel_at`, each sending its webhooks before the browser returns to Pumpkit. Every payment succeeds.
  - It has no clock: a Trial stays a Trial and a `cancel_at` never cancels until something calls the API.
  - `STRIPE_MANAGED_PAYMENTS=true scripts/dev-stack up` runs the stack in Managed Payments mode. Like Stripe, the Emulator then refuses a Checkout that also sends `automatic_tax`, `tax_id_collection` or `customer_update`.
  - When `gateway.py` starts a new Stripe call, add the route to `emulators/stripe.ts`, or the dev stack answers it with a 404.

## Safe mode

- `TRIAL_IDENTITY_KEYS` is a committed throwaway ring supplied only by `compose.emulators.yml`, so local X-account eligibility checks never use an Instance's real keys.

- `PUBLISHER_ENABLED=false`: the publisher process runs but publishes nothing. X API overrides also cover direct Post now and media requests, so those cannot fall back to real X.
- `SMTP_HOST=` and `EMAIL_FROM=`: No active sign-in flow sends email; the retained inactive mail adapter is never called by the main app. Blanking only one leaves SMTP partly configured, and the backend refuses to start. emulate covers Resend, not SMTP, so mail is a custom-Emulator candidate.
- `POSTHOG_ENABLED=false`: the backend sends no analytics events. PostHog is a custom-Emulator candidate.
- twitterapi.io, the LLM endpoint and Jev (TypeSafe's classifier) only read or generate, so nothing is switched off; each is a custom-Emulator candidate.

## E2E data

`make e2e` starts this contract when no `E2E_BASE_URL` is supplied; CI installs the pinned Portless version first. Browser seeds use deterministic X IDs and are CLI-only fixtures that refuse production or a missing local X provider. General backend authorization fixtures use the existing session service directly; focused tests retain the inactive-flow helpers they exercise.

The normal Dev URL uses X-only sign-in through the local provider. Seeded credentials are throwaway, and no Google or magic link route is active. The contract also starts the separate local-only `tests.staged_x_app:create_app` fixture at `scripts/dev-stack staged-x-url` for isolated adapter/protocol checks. That fixture refuses production and missing X overrides and is never imported by `pumpkit.main`. Its callback strips protocol credentials before rendering.

Run only the protocol smoke with `E2E_BASE_URL=$(scripts/dev-stack url) npm --prefix e2e test -- tests/x-sign-in.spec.ts`. It covers fresh/returning sign-in, confirmed-email refusal and cancellation without live X credentials. The full suite remains the final stack check. When reusing data created by older email-based browser seeds, first destroy only this worktree's dev stack and start it again.

Use `e2e/backend.ts` to run scripts from `e2e/seed/` inside this worktree's backend container. They seed local Users, Subscriptions and usage without calling providers. The usage smoke tests need the dummy billing configuration and caps in [CONTRIBUTING.md](../../CONTRIBUTING.md#make-targets); they stub the Stripe-backed catalog response and cancel purchase dialogs before payment.

## Browsers

Chrome, Firefox, Edge, `curl` and Node's `fetch` resolve `*.localhost` on their own. Safari may not: run `portless hosts sync` once when a Dev URL doesn't resolve there.

The staged assembly fetches only the exact local provider avatar URL with a test-owned photo adapter. The production photo adapter keeps its HTTPS-only rule.

## Personal X sign-in on a human-operated stack

Use a dedicated worktree for personal X sign-in. This explicit exception to the
contract's throwaway credentials and ephemeral frontend ports is for a human
checking the real provider. Automated checks always use plain `scripts/dev-stack up`.

1. Configure that worktree's protected `.env` with the OAuth2 confidential app's
   `X_CLIENT_ID` and `X_CLIENT_SECRET` and a persistent `TRIAL_IDENTITY_KEYS` ring.
   Preserve the ring with this local instance's data; do not use the committed
   emulator ring for personal accounts. Keep the existing encryption keys too.
2. Register exactly `http://127.0.0.1:5173/oauth/x/callback` on the X app, preserving
   its other callbacks. X documents HTTP loopback development with `127.0.0.1`.
   The app must grant `tweet.read tweet.write users.read offline.access media.write users.email`,
   and the human account must have a confirmed email. Credential presence alone
   does not prove app entitlement or a successful real sign-in.
3. Run `scripts/dev-stack up --real-x`. For a different registered port, pass the
   exact origin, for example `scripts/dev-stack up --real-x http://127.0.0.1:5175`.
   The port must be free; the script never stops its current owner. Open only the
   returned loopback URL throughout sign-in so browser-bound cookies and the
   callback share an origin.

The main backend and publisher use the real X app credentials and canonical X
endpoints. Stripe and the inactive Google adapter remain emulated, mail and
analytics remain off, and the staged X fixture retains fake credentials and URLs.
The scheduled publisher is disabled. **Post now and media requests target real X**;
this mode does not block manual publishing. Do not use those actions for a sign-in check.

The real stack has its own Compose project and volumes, separate from the default
emulated stack. `.sdlc/dev-stack/` records only the selected mode and public URL
alongside the existing route bookkeeping; it never records credentials. `url`,
`status`, `logs` and `down` retain that selection. `up --real-x` resumes it;
plain `up` refuses, including when called automatically by `make e2e`. No E2E seed
target is written in real mode. Do not point E2E at the personal stack explicitly.

Use `scripts/dev-stack down` to stop it and preserve personal data. To return to
emulation, use another worktree. `scripts/dev-stack destroy` explicitly deletes
this stack's database and media volumes and clears its mode, after which plain
`up` creates an emulated stack. Do not destroy personal data as an automated cleanup
step. Shared Portless proxy settings and other worktrees' routes remain untouched.

Provider setup references: [X Apps](https://docs.x.com/fundamentals/developer-apps)
and [OAuth2 authorization code](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code).

## Personal testing on localhost with real providers

This human-operated mode uses real X, Stripe's sandbox and the configured writing
providers, with a persistent local database and media. It is separate from the
emulated agent stack and the older `--real-x` mode (which still emulates Stripe).
Automated checks always use plain `scripts/dev-stack up` in an emulated worktree.

Use a dedicated worktree and configure its protected root `.env`:

- Set real `X_CLIENT_ID` and `X_CLIENT_SECRET`, preserving the required publishing
  and confirmed-email permissions. Register exactly
  `http://127.0.0.1:5173/oauth/x/callback` on that X app, keeping its other callbacks.
- Set the selected Stripe sandbox's `STRIPE_SECRET_KEY=sk_test_...`,
  `STRIPE_PUBLISHABLE_KEY=pk_test_...`, `STRIPE_WEBHOOK_SECRET` and
  `BILLING_PLAN_KEYS`. Set `BILLING_TOP_UP_KEY` to test top-ups.
  The mode refuses live keys and provider URL overrides; it does not replace them
  with emulator credentials. Use the same sandbox for the CLI, API keys, catalog
  and portal configurations. The startup check validates configuration shape,
  not provider permissions or resource ownership.
- Keep the instance's `FERNET_ENCRYPTION_KEY`, signing secrets and persistent
  `TRIAL_IDENTITY_KEYS` ring with its data. Generate keys once for a new instance;
  never reuse the emulator ring for personal accounts.
- Configure the actual LLM, twitterapi.io and classifier providers as usual.
- To test coupons, explicitly set `COUPONS_ENABLED=true`, a persistent
  `COUPON_IDENTITY_KEYS` ring and that sandbox's
  `STRIPE_COUPON_PORTAL_CONFIGURATION_ID`. Follow [the coupon setup and activation
  guidance](../coupons.md); this isolated test opt-in does not activate production
  coupons. Back up both identity rings with the database.

Configure Stripe's sandbox catalog and tax prerequisites as described in
[Subscriptions](../development.md#subscriptions). Start Stripe CLI forwarding in
another terminal, authenticated to the same sandbox:

```sh
stripe listen --forward-to http://localhost:5173/api/v1/stripe/webhook
```

Put the listener's displayed signing secret into `STRIPE_WEBHOOK_SECRET` in
`.env`, then start or restart the stack so it reads the secret:

```sh
scripts/dev-stack up --personal
# Equivalent: make dev-personal
```

Open only the printed `http://localhost:5173` app address. The dev server briefly
receives X's callback at `127.0.0.1`, then redirects it to the fixed localhost
callback before React loads. Login and reconnect finish on localhost with their
original browser cookies and storage. State, PKCE and browser-binding checks stay
in place. The relay is unavailable in production builds. The dev server marks
responses `X-Pumpkit-Dev-Mode: personal` so E2E refuses this target before seeding
or opening a browser, including from another worktree.

For another port, register its exact X callback first, then run
`scripts/dev-stack up --personal http://localhost:5175` from a fresh dedicated
worktree and change the Stripe forwarding URL to match. Use one personal instance per browser profile: localhost cookies are shared
across ports. Both IPv4 and IPv6 loopback bindings must be available. No Portless installation or route is needed.
The selected port must be free; startup never stops its owner.

The mode sets `PUBLIC_URL` to its selected localhost origin regardless of `.env`'s
`PUBLIC_URL`, so Checkout, portal and other return URLs use localhost too.
Scheduled publishing, mail and analytics remain disabled. **Post now and media
requests use real X.** Writing uses the configured real services.

Personal mode has its own Compose project and volumes. It starts with a fresh
local database; existing emulated or `--real-x` data is never copied or removed.
`url`, `status`, `logs` and `down` remember the selection. `down` preserves data;
`up --personal` resumes it. Plain `up`, including `make dev` and `make e2e`, refuses
to change this worktree's mode. `staged-x-url` is unavailable. Do not run E2E or
seed scripts against personal data. `destroy` explicitly deletes this stack's
volumes; never run it as automated cleanup for a personal stack.

Acceptance: sign in with real X, reconnect the same account, complete sandbox
Checkout and a portal return, redeem a sandbox coupon, observe signed webhook
success, and restart to confirm saved data remains. Transport tests and emulated
checks do not prove real-provider permissions or billing behavior.
