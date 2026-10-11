# Development guide

## Project layout

```
backend/src/pumpkit/
  main.py          the FastAPI app: mounts every area's router and registers the error handlers
  models.py        imports every area's models, so Alembic and the tests see the whole schema
  core/            plumbing every area shares: config, logging, db/ (base, session, URLs), errors, security, rate limiting, analytics, time, ids
  auth/            Users, Sessions, refresh tokens, Google identities, Magic links; Google sign-in, the auth mailer and its templates/
  billing/         Plans and Subscriptions; the billing gateway (Stripe) and the Stripe webhook
  authors/         Inspiration authors and their posts; the X reader (twitterapi.io)
  x_connection/    X connections; the X publisher port (X's API) and X's weighted length count
  support/         the support contact redirect (a router only)
  posts/           Posts and Versions; the LLM port and OpenRouter client
  posts/writing/   the pumpkit-v6 writing workflow: prompts, corpus framing, scrub, writing a Version
  scheduling/      Scheduled posts: rules, publish steps, publishing, and the publisher process
backend/tests/     pytest suite, mirroring the package tree; fixtures in conftest.py
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

Every area is built from the same modules: `router.py` (HTTP only: dependencies, parsing, response shaping), `mediator.py` (orchestration and the transaction), `service.py` (one resource or capability each, with its database access), `schemas.py` (Pydantic request and response models) and `models.py` (SQLAlchemy tables). An area with nothing to orchestrate skips the mediator, and `support` is a router alone. The call direction is `router -> mediator -> service`, never backwards, and no DB queries in routers or mediators.

ADR 0008 orders the areas `core` <- `auth` <- `billing` <- {`authors`, `x_connection`, `support`} <- `posts` <- `scheduling`: an area imports only areas to its left, and only their service, models, schemas and domain modules, never a router or mediator. `core` imports no area. `cd backend && uv run --extra dev lint-imports` checks these rules with the contracts in `backend/pyproject.toml`, and CI runs it. When an endpoint belongs to one area but needs a higher area's data, serve it from the higher area: `GET /x-connection` and `POST /x-connection/authorizations/complete` answer with the count of waiting Scheduled posts, so `scheduling/router.py` serves them, and `x_connection/router.py` keeps starting an authorization and disconnecting.

## Recipes

### Subscriptions

Pumpkit bills only by Subscription (see `docs/adr/0003-subscription-only-billing.md`). Create each Plan as a recurring price in Stripe with a lookup key (for example `pumpkit_pro_monthly`), and list that key in `BILLING_PLAN_KEYS` (see `docs/configuration.md`). Set each price's tax behaviour to inclusive, and set up Stripe Tax in test mode too: Checkout charges VAT and collects VAT IDs, so Stripe refuses to create one without it (see `docs/deployment.md`). Only those Plans appear on the landing page and in the billing dialog (`GET /api/v1/billing/plans`), and Checkout (`POST /api/v1/billing/checkout`) takes nothing but a Plan key: the server resolves the price and always buys one. A User has at most one Running Subscription, and the backend enforces it: before deciding anything, Checkout syncs the User's Subscriptions from Stripe (`billing/service.sync_customer`), so it sees a Subscription no webhook has reported yet, and a User with a Running Subscription gets a `409 Conflict` (they manage it in the billing portal). A User who has never had a Subscription gets a Trial of `BILLING_TRIAL_PERIOD_DAYS` days, once, through that Checkout with a card; the client can't ask for one. The billing service answers both questions (`billing/service.get_subscription_offer`). Starting a Checkout cancels the User's `incomplete` Subscriptions and expires their other open Checkouts, so only the newest attempt can start a Subscription.

Subscribe the Stripe webhook to: `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted` and `checkout.session.completed`. Webhooks are nudges (ADR 0004): each of these events only names the customer that changed, and Pumpkit then lists that customer's Subscriptions from Stripe and syncs its copy, ignoring the event's payload.

Every Stripe call goes through the `BillingGateway` port (`src/pumpkit/billing/gateway.py`): only its Stripe adapter uses the SDK, it returns plain data, and any provider failure is a `BillingProviderError`, which the global handler returns as a 502 with an `error_id`. Routers inject it with `Depends(get_billing_gateway)`; tests get `FakeBillingGateway` through the autouse `fake_billing` fixture, which holds each customer's Subscriptions (`fake_billing.set_subscription(...)`) and signs webhook events (`fake_billing.signed_event(...)`) to post to the endpoint.

Gate an endpoint on being Subscribed with `current_user: User = Depends(require_subscribed_user)` (`src/pumpkit/billing/dependencies.py`): it returns a 403 to a User who isn't, reading only Pumpkit's copy. Tests make the `user` fixture Subscribed by requesting the `subscribed` fixture. On the frontend, `useSubscribed()` (inside `SubscribedProvider`) tells a screen whether to show its tools or a `SubscribePrompt` that opens the Billing dialog; treat a 403 from a write as a cue to call its `refresh()`.

`billing/mediator.handle_webhook` owns the webhook transaction: it records the event for deduplication, locks the customer's User row, syncs the customer's Subscriptions from Stripe (`billing/service.sync_customer`) and commits once. The lock is held across the Stripe call, so webhooks for one customer run one after another. Webhook handlers use the session they are given, never commit, and raise to roll back the whole event so Stripe retries it; a webhook for an unknown customer is logged and skipped.

### Write a Post

Home is where a User writes Posts. `POST /api/v1/posts` takes a Brief and answers with the Post and its first Version once both model calls are done, which can take a minute or two (the Caddyfile allows it). `posts/mediator.start_post` reads the corpus (the newest 20 stored posts of each of the User's Inspiration authors, in list order) through `posts/service.py`, ends the read transaction, writes the Version with `src/pumpkit/posts/writing/versions.py`, and only then stores the Post with its corpus post ids and the attempt, succeeded or failed. A failed attempt is committed before the error is re-raised, so it survives the request's rollback.

`POST /api/v1/posts/{id}/versions` takes Feedback and answers with the next Version. `posts/mediator.add_version` reads the Post's stored corpus (not the User's current Inspiration authors) and its Versions, then runs the revision call: the draft prompt, the corpus, the Brief, each Final as an assistant turn after the Feedback that produced it, and the new Feedback last. Drafts and failed attempts stay out of that conversation. A Post with no Version (its first attempt failed) answers 409.

The prompts in `src/pumpkit/posts/writing/prompts/` are copied word for word from pumpkit-v6, `<creator>` corpus markup included: change them only on purpose, as a prompt change. The writing, humanizing and revising models are constants in `src/pumpkit/posts/writing/constants.py`.

### Schedule a post

A Subscribed User connects X on the Scheduled page (`x_connection/router.py` and `scheduling/router.py`; the X publisher port in `x_connection/x_publisher.py`). `POST /api/v1/scheduled-posts` takes a text and either `publish_at` or `publish_now`. `GET /api/v1/scheduled-posts` takes an optional `state` to list only Scheduled posts in that state. `DELETE` removes a scheduled or Failed one. `scheduling/mediator.py` checks every new Scheduled post in one place: `connection_to_publish_on` (an X connection that doesn't need reconnecting) and `check_monthly_cap`, plus the pure rules in `scheduling/rules.py`: `check_length` (X's weighted count) and `check_publish_at` (a whole minute, one minute to a year ahead, stored in UTC). Reuse them for anything that creates or moves a Scheduled post.

A Final goes to X through the same endpoint: the Schedule and Post now dialogs on each Version (`features/scheduledPosts/FinalToX.tsx`) send the Final's text with `source_version_id`, the Version's id. The backend refuses a Version that isn't the User's and keeps the id, which becomes null if the Version is deleted. The X connection's provider sits in `AppLayout`, so Home and Scheduled share it.

A Scheduled post for later waits in `scheduled` until the publisher picks it up. The publisher is a process of its own (ADR 0007): `python -m pumpkit.scheduling.publisher`, the `publisher` service in `docker-compose.yml` and `infra/pumpkit-publisher.service` in production. Every `PUBLISHER_POLL_INTERVAL_SECONDS` it runs `publisher.run_pass`, which:

1. fails Scheduled posts stuck in `publishing` for over 10 minutes with "Check your X profile" (`scheduling/publishing.fail_stuck`: a publisher died mid-call);
2. claims and publishes the soonest due one (`scheduling/publishing.publish_next_due`, which claims through `scheduling/service.claim_next_due`: `FOR UPDATE SKIP LOCKED` on Postgres, and a conditional update that keeps the claim single anywhere);
3. repeats until nothing is due.

`scheduling/publishing` owns every commit of a publish: it commits the claim and any rotated refresh token before calling X, calls X once, and commits Published or Failed. Its steps live in `scheduling/publish.py`, which flushes and never commits. A 429 or a refused connection (to publish or to refresh the token) means X surely didn't publish, so it goes back in `scheduled` with a doubling backoff from one minute for the publisher to retry, and becomes Failed if it still can't go out 15 minutes after its publish time. Post now publishes within the request through the same `scheduling/publishing` module; when X doesn't take it, the request returns it in `scheduled` and the publisher retries it like any other.

Test the pass by calling `run_pass(db_session_maker, fake_x_publisher, fixed_clock)` directly and checking outcomes through `GET /api/v1/scheduled-posts` (see `backend/tests/scheduling/test_publisher.py`). The `fixed_clock` fixture freezes time at a known instant for tests that write out dates. Under SQLite the row lock is a no-op, so tests of concurrent passes exercise the conditional claim.

### Call an LLM

Set `OPENROUTER_API_KEY`. Mediators reach models through the `LLM` port (`posts/llm.py`): the router injects it with `llm: LLM = Depends(get_llm)` and passes it to the mediator, which calls `await llm.structured(model=..., messages=..., response_model=MyPydanticModel)`. Any provider failure is an `LLMError`, which the global handler returns as a 502 with an `error_id`; a missing key is a 503 naming the variable. Tests get the scripted `FakeLLM` through the autouse `fake_llm` fixture: queue `fake_llm.replies` and read the messages each call received in `fake_llm.calls`.

The port wraps `openrouter_client` (`posts/openrouter.py`), which also has `llm_complete(...)` and `llm_stream(...)` (yielding `StreamDelta`, `ToolCallDelta`, `AssembledToolCall` and `ModelUsage`) for calls that don't fit it.

### Add a page to the shell

Add the page to `SIDEBAR_PAGES` in `frontend/src/features/sidebar/pages.ts`, which gives it an expanded row and a matching icon on the collapsed rail, and add its route under the `AppLayout` route in `frontend/src/App.tsx`. `frontend/src/pages/AppLayout.tsx` holds the shell and the Post, so the Post stays on screen while the User is on another page.

### Edit the user profile

Profile fields are saved through `PATCH /users/me` in `backend/src/pumpkit/auth/router.py`; the logic lives in `backend/src/pumpkit/auth/service/users.py::update_user_profile` (router to service). The UI is `frontend/src/features/account/`.

### Track an event

Add it to `EVENTS` in `frontend/src/lib/analytics.ts`, then call `track('my_event', {...})`.

### Changing the Terms or the Privacy Policy

Each document is a Markdown file per language in `frontend/src/features/legal/documents/` (`terms.en.md`, `terms.it.md`, `privacy.en.md`, `privacy.it.md`), listed with its route and "Last updated" date in `frontend/src/features/legal/documents.ts`. Both languages are equally valid, so they must always say the same thing.

1. Edit the English and the Italian file in the same change, keeping the same sections, clause numbers and `{#anchor}` ids. Links point at those anchors, such as the consent banner's link to `/privacy#cookies`.
2. Set `TERMS_LAST_UPDATED` or `PRIVACY_LAST_UPDATED` in `documents.ts` to the day of the change. Both language versions read it, so the two pages show the same date. For the Terms, set `TERMS_VERSION` in `backend/src/pumpkit/billing/terms.py` to the same date in the same change: checkout refuses any other version with a 409, so Users accept the new Terms before their next checkout (ADR 0010). If a clause the Billing dialog's checkboxes cite moves or is renamed, update `ONEROUS_CLAUSES` and the withdrawal link in `frontend/src/features/billing/TermsAcceptanceFields.tsx`.
3. For a material change, email every User at least 30 days before it applies, as clause 18 of the Terms and the last section of the Privacy Policy promise.

When you add a cookie or a browser storage key (a `storage.ts` key, a cookie the backend sets, or one a new third-party script sets), add a row for it to the cookie tables in both Privacy Policy files, under strictly necessary or Analytics consent, and follow the steps above.

### Branding

To rebrand, change `APP_NAME`, the meta tags and JSON-LD graph in `frontend/index.html`, `frontend/src/assets/brand/*.svg`, the wordmark font (Google Sans Code, bundled from `@fontsource-variable/google-sans-code` in `frontend/src/main.tsx` and declared as `fontFamily.wordmark` in `frontend/tailwind.config.ts`), `frontend/public/*.png`, `backend/src/pumpkit/auth/templates/emails/assets/logo.png`, and the design tokens in `frontend/src/index.css`.

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
