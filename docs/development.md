# Development guide

## Project layout

```
backend/app/
  api/routers/     HTTP endpoints only: auth deps, parsing, response shaping
  api/mediators/   orchestration across services (webhook dispatch, Google and Magic link sign-in)
  api/services/    one resource or capability each: DB access, Subscriptions, users, tokens
  api/configs/     third-party provider configuration (Google)
  core/            settings, security, logging, OpenRouter and PostHog clients, ports (billing gateway, Google sign-in, auth mailer, X reader, X publisher, LLM)
  writing/         the pumpkit-v6 writing workflow: prompts, corpus framing, scrub, writing a Version
  publishing/      publishing Scheduled posts on X (claim, refresh, checks, outcome), the publisher process and X's length count
  db/              SQLAlchemy models, session, database URLs
  schemas/         Pydantic request/response models
  templates/       email templates and assets
  tests/           pytest suite
frontend/src/
  features/        self-contained feature modules (account, billing, inspirationAuthors, posts, scheduledPosts, sidebar, theme, topbar, xConnection)
  components/      shared UI: auth, blocks, brand, ui primitives
  services/        API clients (apiService handles tokens and refresh)
  lib/             analytics, storage, app constants and helpers
  pages/           route-level pages
  contexts/        auth context
e2e/               Playwright tests run against docker compose
infra/             Caddyfile, publisher systemd unit
scripts/           deploy.sh
docs/              deployment guide
```

The call direction in the backend is `router -> mediator -> service`, never backwards, and no DB queries in routers or mediators.

## Recipes

### Subscriptions

Pumpkit bills only by Subscription (see `docs/adr/0003-subscription-only-billing.md`). Create each Plan as a recurring price in Stripe with a lookup key (for example `pumpkit_pro_monthly`), and list that key in `BILLING_PLAN_KEYS` (see `docs/configuration.md`). Only those Plans appear on the landing page and in the billing dialog (`GET /api/v1/billing/plans`), and Checkout (`POST /api/v1/billing/checkout`) takes nothing but a Plan key: the server resolves the price and always buys one. A User has at most one Running Subscription, and the backend enforces it: before deciding anything, Checkout syncs the User's Subscriptions from Stripe (`subscriptions.sync_customer`), so it sees a Subscription no webhook has reported yet, and a User with a Running Subscription gets a `409 Conflict` (they manage it in the billing portal). A User who has never had a Subscription gets a Trial of `BILLING_TRIAL_PERIOD_DAYS` days, once, through that Checkout with a card; the client can't ask for one. The Subscriptions module answers both questions (`subscriptions.get_subscription_offer`). Starting a Checkout cancels the User's `incomplete` Subscriptions and expires their other open Checkouts, so only the newest attempt can start a Subscription.

Subscribe the Stripe webhook to: `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted` and `checkout.session.completed`. Webhooks are nudges (ADR 0004): each of these events only names the customer that changed, and Pumpkit then lists that customer's Subscriptions from Stripe and syncs its copy, ignoring the event's payload.

Every Stripe call goes through the `BillingGateway` port (`core/billing_gateway.py`): only its Stripe adapter uses the SDK, it returns plain data, and any provider failure is a `BillingProviderError`, which the global handler returns as a 502 with an `error_id`. Routers inject it with `Depends(get_billing_gateway)`; tests get `FakeBillingGateway` through the autouse `fake_billing` fixture, which holds each customer's Subscriptions (`fake_billing.set_subscription(...)`) and signs webhook events (`fake_billing.signed_event(...)`) to post to the endpoint.

Gate an endpoint on being Subscribed with `current_user: User = Depends(require_subscribed_user)` (`app/api/dependencies.py`): it returns a 403 to a User who isn't, reading only Pumpkit's copy. Tests make the `user` fixture Subscribed by requesting the `subscribed` fixture. On the frontend, `useSubscribed()` (inside `SubscribedProvider`) tells a screen whether to show its tools or a `SubscribePrompt` that opens the Billing dialog; treat a 403 from a write as a cue to call its `refresh()`.

`mediators/billing.handle_webhook` owns the webhook transaction: it records the event for deduplication, locks the customer's User row, syncs the customer's Subscriptions from Stripe (`subscriptions.sync_customer`) and commits once. The lock is held across the Stripe call, so webhooks for one customer run one after another. Webhook handlers use the session they are given, never commit, and raise to roll back the whole event so Stripe retries it; a webhook for an unknown customer is logged and skipped.

### Write a Post

Home is where a User writes Posts. `POST /api/v1/posts` takes a Brief and answers with the Post and its first Version once both model calls are done, which can take a minute or two (the Caddyfile allows it). `mediators/posts.start_post` reads the corpus (the newest 20 stored posts of each of the User's Inspiration authors, in list order) through `services/posts`, ends the read transaction, writes the Version with `app/writing/versions.py`, and only then stores the Post with its corpus post ids and the attempt, succeeded or failed. A failed attempt is committed before the error is re-raised, so it survives the request's rollback.

`POST /api/v1/posts/{id}/versions` takes Feedback and answers with the next Version. `mediators/posts.add_version` reads the Post's stored corpus (not the User's current Inspiration authors) and its Versions, then runs the revision call: the draft prompt, the corpus, the Brief, each Final as an assistant turn after the Feedback that produced it, and the new Feedback last. Drafts and failed attempts stay out of that conversation. A Post with no Version (its first attempt failed) answers 409.

The prompts in `app/writing/prompts/` are copied word for word from pumpkit-v6, `<creator>` corpus markup included: change them only on purpose, as a prompt change. The writing, humanizing and revising models are constants in `app/writing/constants.py`.

### Schedule a post

A Subscribed User connects X on the Scheduled page (`x_connection` router; the X publisher port in `core/x_publisher.py`). `POST /api/v1/scheduled-posts` takes a text and either `publish_at` or `publish_now`. `GET /api/v1/scheduled-posts` takes an optional `state` to list only Scheduled posts in that state. `DELETE` removes a scheduled or Failed one. `mediators/scheduled_posts` checks every new Scheduled post in one place: `connection_to_publish_on` (an X connection that doesn't need reconnecting), `check_length` (X's weighted count) and `check_publish_at` (a whole minute, one minute to a year ahead, stored in UTC). Reuse them for anything that creates or moves a Scheduled post.

A Final goes to X through the same endpoint: the Schedule and Post now dialogs on each Version (`features/scheduledPosts/FinalToX.tsx`) send the Final's text with `source_version_id`, the Version's id. The backend refuses a Version that isn't the User's and keeps the id, which becomes null if the Version is deleted. The X connection's provider sits in `AppLayout`, so Home and Scheduled share it.

A Scheduled post for later waits in `scheduled` until the publisher picks it up. The publisher is a process of its own (ADR 0007): `python -m app.publishing`, the `publisher` service in `docker-compose.yml` and `infra/pumpkit-publisher.service` in production. Every `PUBLISHER_POLL_INTERVAL_SECONDS` it runs `publisher.run_pass`, which:

1. fails Scheduled posts stuck in `publishing` for over 10 minutes with "check your X profile" (a publisher died mid-call);
2. claims the soonest due one (`services/scheduled_posts.claim_next_due`: `FOR UPDATE SKIP LOCKED` on Postgres, and a conditional update that keeps the claim single anywhere), commits, and hands it to `publish.publish_claimed`;
3. repeats until nothing is due.

`publish_claimed` calls X once and records Published or Failed. A 429 or a refused connection (to publish or to refresh the token) means X surely didn't publish, so it goes back in `scheduled` with a doubling backoff from one minute for the publisher to retry, and becomes Failed if it still can't go out 15 minutes after its publish time. Post now publishes within the request through the same module; when X doesn't take it, the request returns it in `scheduled` and the publisher retries it like any other.

Test the pass by calling `run_pass(db_session_maker, fake_x_publisher, fixed_clock)` directly and checking outcomes through `GET /api/v1/scheduled-posts` (see `tests/publishing/test_publisher.py`). The `fixed_clock` fixture freezes time at a known instant for tests that write out dates. Under SQLite the row lock is a no-op, so tests of concurrent passes exercise the conditional claim.

### Call an LLM

Set `OPENROUTER_API_KEY`. Mediators reach models through the `LLM` port (`core/llm.py`): the router injects it with `llm: LLM = Depends(get_llm)` and passes it to the mediator, which calls `await llm.structured(model=..., messages=..., response_model=MyPydanticModel)`. Any provider failure is an `LLMError`, which the global handler returns as a 502 with an `error_id`; a missing key is a 503 naming the variable. Tests get the scripted `FakeLLM` through the autouse `fake_llm` fixture: queue `fake_llm.replies` and read the messages each call received in `fake_llm.calls`.

The port wraps `openrouter_client` (`core/openrouter.py`), which also has `llm_complete(...)` and `llm_stream(...)` (yielding `StreamDelta`, `ToolCallDelta`, `AssembledToolCall` and `ModelUsage`) for calls that don't fit it.

### Add a page to the shell

Add the page to `SIDEBAR_PAGES` in `frontend/src/features/sidebar/pages.ts`, which gives it an expanded row and a matching icon on the collapsed rail, and add its route under the `AppLayout` route in `frontend/src/App.tsx`. `frontend/src/pages/AppLayout.tsx` holds the shell and the Post, so the Post stays on screen while the User is on another page.

### Edit the user profile

Profile fields are saved through `PATCH` on the users router; the logic lives in `backend/app/api/services/users.py::update_user_profile` (router to service). The UI is `frontend/src/features/account/`.

### Track an event

Add it to `EVENTS` in `frontend/src/lib/analytics.ts`, then call `track('my_event', {...})`.

### Branding

To rebrand, change `APP_NAME` and `VITE_APP_NAME`, the meta tags and JSON-LD graph in `frontend/index.html`, `frontend/src/assets/brand/*.svg`, the wordmark font (Google Sans Code, loaded in `frontend/index.html` and declared as `fontFamily.wordmark` in `frontend/tailwind.config.ts`), `frontend/public/*.png`, `backend/app/templates/emails/assets/logo.png`, and the design tokens in `frontend/src/index.css`.

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
