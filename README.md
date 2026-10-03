# MyApp SaaS template

MyApp SaaS template: FastAPI + React starter with authentication, Stripe subscriptions and one-time purchases, an LLM client, analytics and a single-server deploy.

## What's included

- Magic-link, Google OAuth and password authentication with rotating refresh tokens
- Stripe subscriptions and one-time purchases with idempotent webhooks
- Profile editing with avatar upload
- App shell: sidebar, account, billing, light/dark/system theme
- Landing page with Stripe-driven pricing
- OpenRouter LLM client (library only, no endpoints)
- Optional PostHog analytics and error tracking
- pytest, vitest and Playwright tests
- Deploy script and Caddy configuration for a single server

## Quickstart

```bash
cp .env.example .env && cp backend/.env.example backend/.env && cp frontend/.env.example frontend/.env
# Generate secrets
python3 -c "import secrets; print(secrets.token_urlsafe(48))"          # JWT_SECRET_KEY, POSTGRES_PASSWORD
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # FERNET_ENCRYPTION_KEY
docker compose up --build
```

Fill in the remaining values in the three `.env` files (Resend, Stripe, optionally Google), then open the app at http://localhost:5173 and the API docs at http://localhost:8000/docs.

To receive Stripe webhooks locally:

```bash
stripe listen --forward-to localhost:8000/api/v1/stripe/webhook
```

Use the `whsec_...` secret it prints as `STRIPE_WEBHOOK_SECRET`.

## Upgrading an existing checkout

Migrations were squashed into a single `0001_initial_schema`. Reset your local data before starting again:

```bash
docker compose down -v
docker compose up --build
```

## Environment reference

Variables marked (optional) can be left empty; the app boots without them. Only the database, auth (JWT, Fernet, Google, Resend) and Stripe variables are required.

### Root `.env`

| Variable | Meaning |
| --- | --- |
| `ENV` | `local` or `prod`. With `prod` the database connection requires SSL. |
| `LOG_LEVEL` | Python log level, e.g. `INFO`. |
| `APP_NAME` | Brand name used in emails and server-side copy. |
| `BACKEND_URL`, `BACKEND_PORT` | Public URL and port of the backend. |
| `FRONTEND_URL`, `FRONTEND_PORT` | Public URL and port of the frontend. |
| `CORS_ORIGINS` | Allowed origins, as a quoted JSON list (see note below). |
| `POSTGRES_USER`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` | Database connection parts. |
| `POSTGRES_PASSWORD` | Database password: a random string of at least 32 characters. |

`CORS_ORIGINS` is single-quoted JSON (`'["http://localhost:5173"]'`). `docker compose` `env_file` accepts that form; a plain `docker run --env-file` would keep the quotes as part of the value. The backend builds its sync database URL (used by Alembic) with the `psycopg2` driver explicitly and the async one with `asyncpg`.

### `backend/.env`

| Variable | Meaning |
| --- | --- |
| `JWT_SECRET_KEY` | Random string of at least 32 characters used to sign tokens. |
| `JWT_ALGORITHM` | Signing algorithm, `HS256`. |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime. |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime. |
| `JWT_ISSUER`, `JWT_AUDIENCE` | `iss` / `aud` claims of issued tokens. |
| `COOKIE_MAX_AGE_SECONDS` | Refresh cookie lifetime (2592000 = 30 days). |
| `FERNET_ENCRYPTION_KEY` | 32 url-safe base64-encoded bytes (generate with `Fernet.generate_key()`). |
| `PASSWORD_RESET_TOKEN_DURATION_HOURS`, `PASSWORD_RESET_TOKEN_NUM_BYTES` | Password-reset token lifetime and size. |
| `PASSWORD_MAX_LENGTH` | Maximum accepted password length. |
| `EMAIL_VERIFICATION_TOKEN_DURATION_HOURS`, `EMAIL_VERIFICATION_TOKEN_NUM_BYTES` | Email-verification token lifetime and size. |
| `EMAIL_VERIFICATION_COOKIE_DURATION_SECONDS` | Short-lived cookie holding the email address during verification. |
| `MAGIC_LINK_TOKEN_DURATION_MINUTES`, `MAGIC_LINK_TOKEN_NUM_BYTES` | Magic-link token lifetime and size. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth credentials. |
| `GOOGLE_OAUTH_REDIRECT_URI` | Must match the redirect URI registered in Google Cloud. |
| `GOOGLE_NONCE_TOKEN_NUM_BYTES`, `GOOGLE_CODE_VERIFIER_TOKEN_NUM_BYTES` | Size of the OAuth nonce and PKCE verifier. |
| `GOOGLE_COOKIE_MAX_AGE_SECONDS` | Lifetime of the short-lived PKCE/CSRF cookies during OAuth. |
| `GOOGLE_TOKEN_ENDPOINT_TIMEOUT_SECONDS` | Timeout for Google's token endpoint. |
| `RESEND_API_KEY` | Resend API key for transactional email. |
| `RESEND_NOREPLY_ADDRESS`, `RESEND_SUPPORT_ADDRESS` | Sender and support addresses. |
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` | Stripe API keys. |
| `STRIPE_WEBHOOK_SECRET` | Signing secret of the webhook endpoint. |
| `STRIPE_CHECKOUT_SUCCESS_URL`, `STRIPE_CHECKOUT_CANCEL_URL` | Where Checkout returns after paying or cancelling. |
| `STRIPE_BILLING_PORTAL_RETURN_URL` | Where the customer portal returns. |
| `OPENROUTER_API_KEY` (optional) | Enables the LLM client; without it calls raise `LLMNotConfiguredError`. |
| `POSTHOG_ENABLED` (optional) | `true` to enable server-side analytics and error tracking. |
| `POSTHOG_PROJECT_API_KEY` (optional) | PostHog project key. |
| `POSTHOG_PERSONAL_API_KEY` (optional) | Personal key, used by `scripts/deploy.sh` for deploy annotations. |
| `POSTHOG_HOST` (optional) | PostHog ingestion host. |

### `frontend/.env`

| Variable | Meaning |
| --- | --- |
| `VITE_API_URL` | Backend API base URL, e.g. `http://localhost:8000/api/v1`. Required for builds. |
| `VITE_APP_NAME` | Brand name shown in the UI (default `MyApp`). |
| `VITE_BYPASS_AUTH` | Dev only: treat every route as authenticated. Ignored in production builds. |
| `VITE_POSTHOG_ENABLED` (optional) | `true` to enable browser analytics. |
| `VITE_POSTHOG_KEY` (optional) | PostHog project key. |
| `VITE_POSTHOG_HOST` (optional) | Ingestion host; in production point it at your reverse-proxy path (`https://<domain>/ph-relay`). |
| `VITE_POSTHOG_UI_HOST` (optional) | PostHog UI host, used for links. |

## Project layout

```
backend/app/
  api/routers/     HTTP endpoints only: auth deps, parsing, response shaping
  api/mediators/   orchestration across services (webhook dispatch, purchases, auth flows)
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

See [docs/deployment.md](docs/deployment.md) for server provisioning and `scripts/deploy.sh`.
