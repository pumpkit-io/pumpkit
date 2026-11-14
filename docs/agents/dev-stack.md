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
- X: custom service `pumpkit-x.emulate.pumpkit`. `up` sets paired `X_AUTHORIZE_URL` (browser-facing) and `X_API_URL` (server-to-server), with throwaway X client credentials. Authorization validates the registered local callback, state and S256 PKCE; codes and refresh tokens are single-use. Seeded accounts include Ada, Grace, one account without confirmed email, and the browser fixtures. Ada and the E2E user have a bio, location and website, which `users/me` returns when asked for `description`, `location` and `url`. `GET /_pumpkit/events` reports only operation kinds and fake user IDs; `/_emulate` is its Inspector. No webhooks. Unsupported publishing/media calls return a local refusal rather than reaching X.
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

## Personal testing on localhost with real providers

Humans run the personal instance directly from their checkout:

```sh
docker compose -f compose.dev.yml up --build
```

Open `http://localhost:5173`. Neither `DEV_PUBLIC_URL` nor `DEV_PUBLIC_PORT`
is required. The base configuration keeps the existing `pumpkit-dev` project,
Postgres volume and media volume. Restarting or rebuilding preserves that data.
Agents use `scripts/dev-stack` in a separate worktree; its launcher refuses the
main checkout so it cannot select the personal project's volumes.

Configure the protected root `.env` with real X client credentials and persistent
signing, encryption and identity keys. Register exactly
`http://127.0.0.1:5173/oauth/x/callback` on that X app, retaining its other callbacks.
The app must grant `tweet.read tweet.write users.read offline.access media.write users.email`,
and the human account must have a confirmed email. The dev server receives the
callback at `127.0.0.1`, then redirects to localhost before React loads so login
and reconnect use the original browser cookies and storage. State, PKCE and
browser binding remain enforced. The relay is unavailable in production builds.

The frontend binds IPv4 and IPv6 loopback. It marks responses
`X-Pumpkit-Dev-Mode: personal`, so E2E refuses it before seeding or browser setup,
including when invoked from another worktree. Do not point agent checks at this
address. Use one personal instance per browser profile: localhost cookies are
shared across ports.

Personal testing uses the configured real writing, twitterapi.io and classifier
services. Scheduled publishing follows `PUBLISHER_ENABLED` (default `true`);
Post now and media requests also use real X. Mail and analytics retain their
existing configuration and consent rules. Provider URL overrides are refused in
this personal configuration. Agent stacks keep their throwaway X and Stripe
credentials, generated URLs and disabled publishing, mail and analytics. Their
writing, twitterapi.io and classifier calls can still use real services.

### Stripe sandbox

Billing may be entirely unconfigured. When configured, use one Stripe sandbox's
`sk_test_...` secret, `pk_test_...` publishable key, webhook secret and catalog keys.
Personal startup rejects live Stripe credentials. The backend and publisher
validate settings before serving or publishing. Production Stripe configuration
is unchanged. Configure the catalog, seller mode and tax prerequisites described
in [Subscriptions](../development.md#subscriptions); keep the CLI, catalog and
portal in the same sandbox.

Forward its webhooks from another terminal:

```sh
stripe listen --forward-to http://localhost:5173/api/v1/stripe/webhook
```

Put the listener's signing secret in `STRIPE_WEBHOOK_SECRET` and recreate the
services with the Compose command above. To test coupons, explicitly configure
`COUPONS_ENABLED`, a persistent `COUPON_IDENTITY_KEYS` ring and the sandbox portal
configuration, following [coupon setup](../coupons.md). Keep both identity rings
with the database across restarts.

### Optional port change

For a different port, set `DEV_PUBLIC_PORT=5175`; the default public URL becomes
`http://localhost:5175`. Register the matching
`http://127.0.0.1:5175/oauth/x/callback` on X and adjust Stripe forwarding. The
optional `DEV_PUBLIC_URL` overrides that origin; keep it consistent with the
published localhost port. The main `.env`'s `PUBLIC_URL` is overridden for local
Compose, so it may retain the production origin.

Stop personal testing with `docker compose -f compose.dev.yml down`. This keeps
data. Avoid `down -v` unless intentionally deleting the personal database and media.

### Retired startup modes and existing data

`make dev-personal`, `scripts/dev-stack up --personal`, `--real-x` and their
Compose overrides have been removed. Plain Compose is the personal workflow;
`make dev` and `scripts/dev-stack up` are the agent workflow. Retired flags fail
with the replacement command. Saved retired mode state refuses all managed
operations before touching Docker or routes; use a fresh agent worktree instead.
No retired containers, volumes or state are deleted or migrated automatically.

The retired modes used separate projects ending in `-personal` or `-real-x`.
Plain Compose resumes only `pumpkit-dev` data. If old data matters, inspect
`docker ps -a --format '{{.Names}}'` and `docker volume ls` to identify its project.
Back up that project's database, media and original `.env` keys before recovery.
For an existing database container, start only that database container if needed
and use `docker exec <db-container> pg_dump -U <db-user> <db-name>` to take a dump.

To deliberately resume old volumes with the new personal setup, stop the old
project's containers explicitly, use its original protected `.env`, and run
`docker compose -p <old-project-name> -f compose.dev.yml up --build`. The named
Postgres and media volumes are selected by that project name; the backend applies
current migrations. This explicit recovery changes which data is used, so verify
the project and backup first. It is not part of automated upgrade or cleanup.
Generated Portless routes left by a retired stack can be inspected with
`portless list` and removed individually after that stack is stopped.

Acceptance: real X sign-in and same-account reconnect, sandbox Checkout and portal
return, webhook success, and restart with retained data. Emulator and transport
tests do not prove X app permissions or sandbox catalog ownership.

Provider references: [X Apps](https://docs.x.com/fundamentals/developer-apps) and
[OAuth2 authorization code](https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code).
