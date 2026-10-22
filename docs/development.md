# Development guide

## Project layout

```
backend/src/pumpkit/
  main.py          the FastAPI app: mounts every area's router and the MCP endpoint, and registers the error handlers
  mcp_server.py    the MCP server: every area's tools behind API key authentication, the access gate and per-User limits
  models.py        imports every area's models, so Alembic and the tests see the whole schema
  core/            plumbing every area shares: config, logging, db/ (base, session, URLs), errors, security, rate limiting, analytics, time, ids, MCP tools, the classifier port (Jev)
  auth/            Users, Sessions, refresh tokens, Google identities, Magic links; Google sign-in, the auth mailer and its templates/
  billing/         Plans and Subscriptions; the billing gateway (Stripe) and the Stripe webhook
  authors/         Inspiration authors and their posts; the X reader (twitterapi.io)
  x_connection/    X connections; the X publisher port (X's API) and X's weighted length count
  support/         the support contact redirect (a router only)
  posts/           Posts and Versions; the LLM port and OpenAI-compatible client
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
e2e/               Playwright tests run against compose.dev.yml
infra/web/         the web image: Dockerfile, Caddyfile, start-up steps, PostHog relay snippet
scripts/           setup.sh (writes .env), check-stack.sh (smoke checks), release notes
docs/              configuration, self-hosting, releasing, ADRs
```

Every area is built from the same modules: `router.py` (HTTP only: dependencies, parsing, response shaping), `mediator.py` (orchestration and the transaction), `service.py` (one resource or capability each, with its database access), `schemas.py` (Pydantic request and response models) and `models.py` (SQLAlchemy tables). An area with nothing to orchestrate skips the mediator, and `support` is a router alone. The call direction is `router -> mediator -> service`, never backwards, and no DB queries in routers or mediators.

ADR 0008 orders the areas `core` <- `auth` <- `billing` <- {`authors`, `x_connection`, `support`} <- `posts` <- `scheduling`: an area imports only areas to its left, and only their service, models, schemas and domain modules, never a router or mediator. `core` imports no area. `cd backend && uv run --extra dev lint-imports` checks these rules with the contracts in `backend/pyproject.toml`, and CI runs it. When an endpoint belongs to one area but needs a higher area's data, serve it from the higher area: `GET /x-connection` and `POST /x-connection/authorizations/complete` answer with the count of waiting Scheduled posts, so `scheduling/router.py` serves them, and `x_connection/router.py` keeps starting an authorization and disconnecting.

## Recipes

### Subscriptions

Pumpkit bills only by Subscription (see `docs/adr/0003-subscription-only-billing.md`). Create each Plan as a recurring price in Stripe with a lookup key (for example `pumpkit_pro_monthly`), and list that key in `BILLING_PLAN_KEYS` (see `docs/configuration.md`). Set each price's tax behaviour to inclusive, and set up Stripe Tax in test mode too: Checkout charges VAT and collects VAT IDs, so Stripe refuses to create one without it (see [Selling Plans](self-hosting.md#selling-plans)). Add a registration in test mode as well, or every test Checkout charges no tax. Checkout always passes `managed_payments[enabled]=false` (`billing/gateway.py`): whoever runs the Instance is the seller, and Stripe's Managed Payments, on by default for new accounts, would make Stripe the seller instead and refuse prices whose product has no tax code. Only the Plans in `BILLING_PLAN_KEYS` appear on the landing page and in the billing dialog (`GET /api/v1/billing/plans`), and Checkout (`POST /api/v1/billing/checkout`) takes nothing but a Plan key: the server resolves the price and always buys one. A User has at most one Running Subscription, and the backend enforces it: before deciding anything, Checkout syncs the User's Subscriptions from Stripe (`billing/service.sync_customer`), so it sees a Subscription no webhook has reported yet, and a User with a Running Subscription gets a `409 Conflict` (they manage it in the billing portal). A User who has never had a Subscription gets a Trial of `BILLING_TRIAL_PERIOD_DAYS` days, once, through that Checkout with a card; the client can't ask for one. The billing service answers both questions (`billing/service.get_subscription_offer`). Starting a Checkout cancels the User's `incomplete` Subscriptions and expires their other open Checkouts, so only the newest attempt can start a Subscription.

Subscribe the Stripe webhook to: `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted` and `checkout.session.completed`. Webhooks are nudges (ADR 0004): each of these events only names the customer that changed, and Pumpkit then lists that customer's Subscriptions from Stripe and syncs its copy, ignoring the event's payload.

Every Stripe call goes through the `BillingGateway` port (`src/pumpkit/billing/gateway.py`): only its Stripe adapter uses the SDK, it returns plain data, and any provider failure is a `BillingProviderError`, which the global handler returns as a 502 with an `error_id`. Routers inject it with `Depends(get_billing_gateway)`; tests get `FakeBillingGateway` through the autouse `fake_billing` fixture, which holds each customer's Subscriptions (`fake_billing.set_subscription(...)`) and signs webhook events (`fake_billing.signed_event(...)`) to post to the endpoint.

Gate an endpoint on being Subscribed with `current_user: User = Depends(require_subscribed_user)` (`src/pumpkit/billing/dependencies.py`): it returns a 403 to a User who isn't, reading only Pumpkit's copy. Tests make the `user` fixture Subscribed by requesting the `subscribed` fixture. On the frontend, `useSubscribed()` (inside `SubscribedProvider`) tells a screen whether to show its tools or a `SubscribePrompt` that opens the Billing dialog; treat a 403 from a write as a cue to call its `refresh()`.

An Instance without the Stripe billing group sells no Plans (ADR 0011): `billing/service.sells_plans()` is false, `require_subscribed_user` and the publisher's check let every User through (`billing/service.has_access`), and the billing routes and the webhook answer 404. The frontend reads `sells_plans` from `useInstance()`: `useSubscribed()` reports every User as Subscribed, and the Billing dialog, the Billing menu item, the `/billing` routes and the landing page's pricing are left out. Tests switch billing off with the `sells_no_plans` fixture, or by rendering with an Instance whose `sells_plans` is false.

`billing/mediator.handle_webhook` owns the webhook transaction: it records the event for deduplication, locks the customer's User row, syncs the customer's Subscriptions from Stripe (`billing/service.sync_customer`) and commits once. The lock is held across the Stripe call, so webhooks for one customer run one after another. Webhook handlers use the session they are given, never commit, and raise to roll back the whole event so Stripe retries it; a webhook for an unknown customer is logged and skipped.

### Write a Post

Home is where a User writes Posts. `POST /api/v1/posts` takes a Brief and answers with the Post and its first Version once its three model calls are done, which can take a minute or two (the Caddyfile allows it). `posts/mediator.start_post` reads the corpus (the newest 20 stored posts of each of the User's Inspiration authors, in list order) through `posts/service.py`, ends the read transaction, writes the Version with `src/pumpkit/posts/writing/versions.py`, and only then stores the Post with its corpus post ids and the attempt, succeeded or failed. A failed attempt is committed before the error is re-raised, so it survives the request's rollback.

`POST /api/v1/posts/{id}/versions` takes Feedback and answers with the next Version. `posts/mediator.add_version` reads the Post's stored corpus (not the User's current Inspiration authors) and its Versions, then runs the revision call: the draft prompt, the corpus, the Brief, each Final as an assistant turn after the Feedback that produced it, and the new Feedback last. Drafts and failed attempts stay out of that conversation. A Post with no Version (its first attempt failed) answers 409.

The first Version's three calls are the draft call, the hook call and the humanizer call. After the scrub, the hook call (`prompts/hook.py`, on `LLM_HOOKING_MODEL`) reads the Draft and picks a Hook from the curated library in its system prompt, answering with the library id of the Draft's current opening (`current_hook_name`), a mode (`keep`, `replace` or `prepend`), the library id of the Hook it writes (`replacing_hook_name`, which may equal the current one when it rewords the opening), the opening it replaces and the Hook. Fields that don't apply are null. `writing/hook.py` splices it in, so the text after the Hook stays as the draft call wrote it, and the humanizer gets the Draft with the Hook. Any failure (the call raising, an unknown id, a missing Hook or replacing id on `replace` or `prepend`, a `replaced_opening` that isn't a prefix of the Draft, a result over `POST_MAX_CHARS`) is logged and the Draft goes on without a Hook; the attempt's `current_hook_name`, `replacing_hook_name`, `hooking_model` and `hooking_usage` then stay null. `hook_answer` keeps the hook call's answer as it came whenever the call returned one, refused splices included, so the prompt can be tuned against what the model actually chose. Tests that write a first Version script the hook reply between the other two, usually `keep_hook()` from `tests/posts/hook_replies.py`.

A Feedback Version asks Jev before its hook step. After the revision call and the scrub, `writing/versions.py` sends Jev one `choice` question (`prompts/hook_check.py`) with a `state` holding the conversation the User saw (the Brief, then each Final as `from: "pumpkit"` and the Feedback after it as `from: "user"`, ending with the latest Feedback) and the scrubbed revision as `latest_draft`. The hook step runs only when the top label is `new_hook`, with no confidence threshold; its messages are the first Version's plus the latest Feedback before the Draft, and its splice and fallbacks are the same. On `keep_hook` or `user_wrote_hook`, and whenever Jev is not configured, raises or times out (logged), the scrubbed revision goes to the humanizer as it is. The attempt stores the top label in `hook_check`, every label's probability in `hook_check_probabilities` and the Jev version in `hook_check_model`, all null when Jev wasn't asked or didn't answer. Tests script Jev with `fake_classifier.replies`; left unscripted it raises, so the hook step is skipped.

The draft, humanizer and revision prompts in `src/pumpkit/posts/writing/prompts/` are copied word for word from pumpkit-v6, `<creator>` corpus markup included, except for the humanizer's paragraph that keeps the Hook; the hook prompt was written for Pumpkit. Change them only on purpose, as a prompt change. Each call's model is an `LLM_*_MODEL` setting (`core/config.py`).

### Schedule a post

A Subscribed User connects X on the Scheduled page (`x_connection/router.py` and `scheduling/router.py`; the X publisher port in `x_connection/x_publisher.py`). `POST /api/v1/scheduled-posts` takes a text or a `source_version_id`, either `publish_at` or `publish_now`, and a `community` (its ID or pasted URL) or none for the profile. `PATCH` takes what changes: a `community` string moves it to that Community, `null` back to the profile, and leaving it out keeps its Destination. `GET /api/v1/scheduled-posts` takes an optional `state` to list only Scheduled posts in that state. `DELETE` removes a scheduled or Failed one.

The router and the MCP tools in `scheduling/tools.py` only map their arguments onto one mediator interface: `mediator.create_scheduled_post` takes a `NewScheduledPost` and `mediator.edit_scheduled_post` a `ScheduledPostEdit`, frozen dataclasses in `scheduling/rules.py` whose constructors refuse a request that gives both or neither of text and a Version, both or neither of a time and publish now, or (for an edit) nothing to change. An edit's Destination change is `KeepDestination`, `ToProfile` or `ToCommunity(pasted)`. The request schemas keep only wire concerns: field limits, aware datetimes, `extra="forbid"`.

The mediator then checks, in order, the X connection (`connection_to_publish_on`), the copied Final, the length (`rules.check_length`, X's weighted count), the time (`rules.check_publish_at`: a whole minute, one minute to a year ahead, stored in UTC) and the cap (`check_monthly_cap`). Only then does it look up the Community's name through `XReader`, so a refused request makes no twitterapi.io call; an unknown Community is refused, and a failed or unconfigured lookup stores no name.

Test a rule in `backend/tests/scheduling/test_mediator.py`, and keep one case of each refusal in the route and tool suites. `await connect_x()` (a fixture in `tests/conftest.py`) gives `user` an X connection to `fake_x_publisher.account` without the authorization's requests, at the time `get_clock` reads, so request the clock fixture first.

A Final goes to X through the same endpoint: the Schedule and Post now dialogs on each Version (`features/scheduledPosts/FinalToX.tsx`) send only `source_version_id`, the Version's id, and the backend copies its Final. The backend refuses a Version that isn't the User's and keeps the id, which becomes null if the Version is deleted. The X connection's provider sits in `AppLayout`, so Home and Scheduled share it.

A Scheduled post for later waits in `scheduled` until the publisher picks it up. The publisher is a process of its own (ADR 0007): `python -m pumpkit.scheduling.publisher`, the `publisher` service in `compose.dev.yml` and `compose.yml`. Every `PUBLISHER_POLL_INTERVAL_SECONDS` it runs `publisher.run_pass`, which:

1. fails Scheduled posts stuck in `publishing` for over 10 minutes with "Check your X profile" (`scheduling/publishing.fail_stuck`: a publisher died mid-call);
2. claims and publishes the soonest due one (`scheduling/publishing.publish_next_due`, which claims through `scheduling/service.claim_next_due`: `FOR UPDATE SKIP LOCKED` on Postgres, and a conditional update that keeps the claim single anywhere);
3. repeats until nothing is due.

`scheduling/publishing` owns every commit of a publish: it commits the claim and any rotated refresh token before calling X, calls X once, and commits Published or Failed. Its steps live in `scheduling/publish.py`, which flushes and never commits. A 429 or a refused connection (to publish or to refresh the token) means X surely didn't publish, so it goes back in `scheduled` with a doubling backoff from one minute for the publisher to retry, and becomes Failed if it still can't go out 15 minutes after its publish time. Post now publishes within the request through the same `scheduling/publishing` module; when X doesn't take it, the request returns it in `scheduled` and the publisher retries it like any other.

Test the pass by calling `run_pass(db_session_maker, fake_x_publisher, fixed_clock)` directly and checking outcomes through `GET /api/v1/scheduled-posts` (see `backend/tests/scheduling/test_publisher.py`). The `fixed_clock` fixture freezes time at a known instant for tests that write out dates. Under SQLite the row lock is a no-op, so tests of concurrent passes exercise the conditional claim.

### Refuse a request

A mediator serves both the web routes and the MCP tools, so it refuses with one of the bases in `core/errors.py` rather than an `HTTPException`: `NotFoundError` (404), `ConflictError` (409), `RefusedError` (422) or `BadRequestError` (400). Each takes the `detail` the User reads, word for word on the web and in a tool error. Pass `fix_page`, a web app path, when the User fixes the refusal in the web app, as the X connection refusals do with `fix_page=SCHEDULED_PAGE` (`/scheduled`, in `scheduling/mediator.py`): the HTTP body then carries the full URL as `url` beside `detail`, built from `PUBLIC_URL`, and a tool error appends it to the text. Raise a base directly, and subclass it only when some code catches that refusal. An MCP tool reads an `HTTPException` as an unexpected error, so only web-only code such as `auth` raises one. Scheduling's pure rules raise `RuleBroken` (a `RefusedError`) and `MonthFull` (a `ConflictError`) from `scheduling/rules.py`.

### Add an MCP tool

Claude Code reaches Pumpkit through the MCP endpoint at `POST /api/v1/mcp` (ADR 0012; the user guide is `docs/claude-code.md`). A tool lives in its area's `tools.py`, beside the router, and calls only that area's mediator, as the router does. `authors/tools.py` is the example to copy.

1. Write the tool as an async function whose first parameter is `call: ToolCall[User]` (`core/mcp_tools.py`), followed by the tool's arguments. Its name is the tool's name (a snake_case verb), its docstring is the description Claude Code reads, its arguments become the input schema, and its return type, a response schema, becomes the output schema. `call.user`, `call.db` and `call.now` are what a route gets from `get_current_user`, `get_async_db` and `clock()`; `await call.provide(get_x_reader)` gives any other provider, honouring the app's dependency overrides, so the tests' fakes apply.
2. Validate input as the route does: build the route's request schema (`InspirationAuthorAddRequest(handle=handle)`) so its checks and messages are the same.
3. Add an `McpTool(fn, rate=..., annotations=...)` to the module's `TOOLS` list. Use the web route's rate where it has one, through the area's `WRITE_RATE` in `schemas.py`, and `READ_ONLY_RATE` for tools that only read. Pick `READ_ONLY`, `ADDITIVE` or `DESTRUCTIVE`: clients ask the User before a destructive tool, and treat a tool without annotations as destructive. Set `needs_access=False` only for a browser-only tool that just answers with a web app link, as a `LinkToolResponse` (`core/schemas.py`): `connect_x` in `scheduling/tools.py` and `manage_subscription` in `billing/tools.py`.

`pumpkit/mcp_server.py` registers every module's `TOOLS` and wraps each tool: it counts the call against the User's limit for that tool, checks access with `billing/service.has_access` (a tool error with the subscribe link otherwise), opens the call's session, and turns what the tool raises into a tool error. An `AppError` or a request schema's `ValidationError` keeps the web route's `detail` word for word, then the fix page's `url` when there is one, and `retry_at` when there is one; a reported error goes to PostHog with an `error_id`, as the global handler sends it. So a tool raises the mediator's refusals and never catches them. Tool calls send no product events (ADR 0012).

import-linter lets only `pumpkit.mcp_server` import a tools module, and keeps a tools module from importing its router or the router from importing it.

Test a tool through the endpoint with the `mcp` fixture: Claude Code connected with an API key that `user` created through `POST /api/v1/api-keys` after a real sign-in, on a client without the `get_current_user` override. Request `subscribed` or `sells_no_plans` before it, since creating a key needs access. `await mcp.call_tool("add_inspiration_author", handle="levelsio")` returns the result, with `structuredContent` holding the response schema; `error_text(result)` (`tests/mcp_client.py`) asserts a tool error and returns its text. See `backend/tests/authors/test_inspiration_author_tools.py`.

### Call an LLM

Set `LLM_API_KEY` (and `LLM_BASE_URL` for an endpoint other than OpenRouter). Mediators reach models through the `LLM` port (`posts/llm.py`): the router injects it with `llm: LLM = Depends(get_llm)` and passes it to the mediator, which calls `await llm.structured(model=..., messages=..., response_model=MyPydanticModel)`. Any provider failure is an `LLMError`, which the global handler returns as a 502 with an `error_id`; a missing key is a 503 naming the variable. Tests get the scripted `FakeLLM` through the autouse `fake_llm` fixture: queue `fake_llm.replies` and read the messages each call received in `fake_llm.calls`.

The port wraps `llm_client` (`posts/llm_client.py`), which also has `llm_complete(...)` and `llm_stream(...)` (yielding `StreamDelta`, `ToolCallDelta`, `AssembledToolCall` and `ModelUsage`) for calls that don't fit it.

### Ask Jev a question

A labelled question goes to Jev, not to an LLM (ADR 0013). Set `TYPESAFE_API_KEY` to try it for real. Mediators reach Jev through the `Classifier` port (`core/classifier.py`): the router injects it with `classifier: Classifier = Depends(get_classifier)` and passes it to the mediator, which asks:

```python
classification = await classifier.classify(
    state={"conversation": [...], "latest_draft": draft},
    questions={"opening": ChoiceQuestion(instructions="...", criteria={"new_hook": "...", "keep_hook": "..."})},
    model=settings.TYPESAFE_MODEL,
)
answer = classification.answers["opening"]  # a ChoiceAnswer: choice, confidence, probabilities
```

`state` is any JSON value, and each question's name keys its answer. `classification.model` is the Jev version that answered, and `classification.usage` its token counts. The adapter waits 5 seconds and retries once on a timeout, a lost connection, a 429 or a 529. Jev is optional, so the caller catches `ClassifierError` (the provider failed or gave an answer that doesn't fit the questions) and `ClassifierNotConfiguredError` (no key), a subclass of it, and takes its cautious path instead of failing the request. Tests get the scripted `FakeClassifier` through the autouse `fake_classifier` fixture: queue `fake_classifier.replies` (answers by question name, or an exception) and read each call's state, questions and model in `fake_classifier.calls`. With no reply queued it raises `ClassifierError`, so a test that doesn't script Jev sees the cautious path. The adapter's own tests are in `backend/tests/core/test_classifier.py`.

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
make test   # backend pytest and frontend vitest
make e2e    # starts the dev stack if it is down, then runs Playwright against it
```

Before the first `make e2e`, run `cd e2e && npm install && npx playwright install chromium`. CONTRIBUTING lists every target.

`make smoke` builds and starts the production stack from `.env`, then runs `scripts/check-stack.sh` against it. To check a stack that is already running, run `sh scripts/check-stack.sh [BASE_URL]` (default `http://localhost:8080`; it needs curl). Set `POSTHOG_RELAY=true` when the stack runs the PostHog relay, and `EXPECT_SEARCH_INDEXING=true` when it has `ALLOW_SEARCH_INDEXING=true`.

The e2e suite opens the Billing dialog, so its Instance must sell Plans: set the Stripe billing group in `.env`. [CONTRIBUTING](../CONTRIBUTING.md#make-targets) gives dummy values that work.

If host port 5432 is already taken, add a local compose override that remaps the db service and point `COMPOSE_FILE` at it:

```yaml
# compose.dev.override.local.yml
services:
  db:
    ports: !override ["55433:5432"]
```

```bash
make dev DEV_COMPOSE="docker compose -f compose.dev.yml -f compose.dev.override.local.yml"
```

## Self-hosting and releases

Running an Instance: [self-hosting.md](./self-hosting.md). Cutting a release and deploying pumpkit.io: [releasing.md](./releasing.md).
