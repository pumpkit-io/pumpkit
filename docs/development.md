# Development guide

## Project layout

```
backend/app/
  api/routers/     HTTP endpoints only: auth deps, parsing, response shaping
  api/mediators/   orchestration across services (webhook dispatch, Google and Magic link sign-in)
  api/services/    one resource or capability each: DB access, Subscriptions, users, tokens
  api/configs/     third-party provider configuration (Google)
  core/            settings, security, logging, OpenRouter and PostHog clients, ports (billing gateway, Google sign-in, auth mailer, X reader)
  db/              SQLAlchemy models, session, database URLs
  schemas/         Pydantic request/response models
  templates/       email templates and assets
  tests/           pytest suite
frontend/src/
  features/        self-contained feature modules (account, billing, inspirationAuthors, sidebar, theme, topbar)
  components/      shared UI: auth, blocks, brand, ui primitives
  services/        API clients (apiService handles tokens and refresh)
  lib/             analytics, storage, app constants and helpers
  pages/           route-level pages
  contexts/        auth context
e2e/               Playwright tests run against docker compose
infra/             Caddyfile
scripts/           deploy.sh
docs/              deployment guide
```

The call direction in the backend is `router -> mediator -> service`, never backwards, and no DB queries in routers or mediators.

## Building your app

### Subscriptions

Pumpkit bills only by Subscription (see `docs/adr/0003-subscription-only-billing.md`). Create each Plan as a recurring price in Stripe with a lookup key (for example `pumpkit_pro_monthly`), and list that key in `BILLING_PLAN_KEYS` (see `docs/configuration.md`). Only those Plans appear on the landing page and in the billing dialog (`GET /api/v1/billing/plans`), and Checkout (`POST /api/v1/billing/checkout`) takes nothing but a Plan key: the server resolves the price and always buys one. A User has at most one Running Subscription, and the backend enforces it: before deciding anything, Checkout syncs the User's Subscriptions from Stripe (`subscriptions.sync_customer`), so it sees a Subscription no webhook has reported yet, and a User with a Running Subscription gets a `409 Conflict` (they manage it in the billing portal). A User who has never had a Subscription gets a Trial of `BILLING_TRIAL_PERIOD_DAYS` days, once, through that Checkout with a card; the client can't ask for one. The Subscriptions module answers both questions (`subscriptions.get_subscription_offer`). Starting a Checkout cancels the User's `incomplete` Subscriptions and expires their other open Checkouts, so only the newest attempt can start a Subscription.

Subscribe the Stripe webhook to: `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted` and `checkout.session.completed`. Webhooks are nudges (ADR 0004): each of these events only names the customer that changed, and Pumpkit then lists that customer's Subscriptions from Stripe and syncs its copy, ignoring the event's payload.

Every Stripe call goes through the `BillingGateway` port (`core/billing_gateway.py`): only its Stripe adapter uses the SDK, it returns plain data, and any provider failure is a `BillingProviderError`, which the global handler returns as a 502 with an `error_id`. Routers inject it with `Depends(get_billing_gateway)`; tests get `FakeBillingGateway` through the autouse `fake_billing` fixture, which holds each customer's Subscriptions (`fake_billing.set_subscription(...)`) and signs webhook events (`fake_billing.signed_event(...)`) to post to the endpoint.

Gate an endpoint on being Subscribed with `current_user: User = Depends(require_subscribed_user)` (`app/api/dependencies.py`): it returns a 403 to a User who isn't, reading only Pumpkit's copy. Tests make the `user` fixture Subscribed by requesting the `subscribed` fixture. On the frontend, `useSubscribed()` (inside `SubscribedProvider`) tells a screen whether to show its tools or a `SubscribePrompt` that opens the Billing dialog; treat a 403 from a write as a cue to call its `refresh()`.

`mediators/billing.handle_webhook` owns the webhook transaction: it records the event for deduplication, locks the customer's User row, syncs the customer's Subscriptions from Stripe (`subscriptions.sync_customer`) and commits once. The lock is held across the Stripe call, so webhooks for one customer run one after another. Webhook handlers use the session they are given, never commit, and raise to roll back the whole event so Stripe retries it; a webhook for an unknown customer is logged and skipped.

### Call an LLM

Set `OPENROUTER_API_KEY`, then from a mediator:

```python
from app.core.openrouter import openrouter_client

result = await openrouter_client.llm_complete(
    model="openai/gpt-5", messages=[{"role": "user", "content": "Hi"}]
)
```

There is also `llm_stream(...)`, which yields `StreamDelta`, `ToolCallDelta`, `AssembledToolCall` and `ModelUsage`, and `llm_structured(..., response_model=MyPydanticModel)`.

### Add a page to the shell

Add navigation rows in `frontend/src/features/sidebar/Sidebar.tsx` and render your feature in the main area of `frontend/src/pages/Home.tsx`, or add a protected route in `frontend/src/App.tsx`.

### Edit the user profile

Profile fields are saved through `PATCH` on the users router; the logic lives in `backend/app/api/services/users.py::update_user_profile` (router to service). The UI is `frontend/src/features/account/`.

### Track an event

Add it to `EVENTS` in `frontend/src/lib/analytics.ts`, then call `track('my_event', {...})`.

### Branding

To rebrand, change `APP_NAME` and `VITE_APP_NAME`, the meta tags in `frontend/index.html`, `frontend/src/assets/brand/*.svg`, `frontend/public/*.png`, `backend/app/templates/emails/assets/logo.png`, and the design tokens in `frontend/src/index.css`.

## Testing

```bash
cd backend && uv sync --extra dev && uv run --extra dev pytest
cd frontend && npm test
# e2e, run from the repo root with docker compose
docker compose up -d && cd e2e && npm install && npx playwright install chromium && npm test
```

If host port 5432 is already taken, add a local compose override that remaps the db service and point `COMPOSE_FILE` at it:

```yaml
# docker-compose.override.local.yml
services:
  db:
    ports: !override ["55433:5432"]
```

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.override.local.yml docker compose up -d
```

## Deployment

See [deployment.md](./deployment.md) for server provisioning and `scripts/deploy.sh`.
