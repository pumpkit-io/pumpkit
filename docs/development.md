# Development guide

## Project layout

```
backend/app/
  api/routers/     HTTP endpoints only: auth deps, parsing, response shaping
  api/mediators/   orchestration across services (webhook dispatch, purchases, Google and Magic link sign-in)
  api/services/    one resource or capability each: DB access, Stripe, users, tokens
  api/hooks/       extension points you implement (purchase hooks)
  api/configs/     third-party provider configuration (Google)
  core/            settings, security, logging, products, OpenRouter and PostHog clients
  db/              SQLAlchemy models, session, database URLs
  schemas/         Pydantic request/response models
  templates/       email templates and assets
  tests/           pytest suite
frontend/src/
  features/        self-contained feature modules (account, billing, sidebar, theme, topbar)
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

### Sell one-time products

Edit `PRODUCTS` in `backend/app/core/purchases.py`, then implement the hooks in `backend/app/api/hooks/purchases.py`:

- `on_purchase_paid(db, purchase)` grants the product.
- `on_purchase_reversed(db, purchase, reason)` revokes it; `reason` is `refunded`, `partially_refunded` or `disputed`.
- `on_purchase_reinstated(db, purchase)` re-grants it when a dispute is won.

The hooks run inside the webhook transaction: use the session you are given, never commit, and raise to make Stripe retry the event. Each status transition fires its hook once.

A purchase starts `pending` and becomes `paid` when Checkout completes. A refund moves it to `refunded` (or `partially_refunded` for a partial one; a later full refund moves it on to `refunded`). A dispute marks it `disputed`; if you win, funds are reinstated and it returns to `paid` or `partially_refunded`. It becomes `failed` only when the Checkout session expires, an async payment fails, or the paid amount or currency does not match the catalog. A failed card attempt alone does not fail the purchase, since Checkout lets the customer retry with another card.

Amounts assume 2-decimal currencies (minor units / 100); zero- and three-decimal currencies need extra handling.

Subscribe the Stripe webhook to: `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `checkout.session.completed`, `checkout.session.expired`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `charge.refunded`, `charge.dispute.funds_withdrawn`, `charge.dispute.funds_reinstated`, `payment_intent.payment_failed`.

### Subscriptions

Create products with recurring prices in Stripe. They appear on the landing page and in the billing dialog automatically.

Cardless trials are available via `POST /api/v1/stripe/trial`, but they are not wired into the billing dialog.

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

`APP_NAME` and `VITE_APP_NAME`, the meta tags in `frontend/index.html`, `frontend/src/assets/brand/*.svg`, `frontend/public/*.png`, `backend/app/templates/emails/assets/logo.png`, and the design tokens in `frontend/src/index.css`.

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
