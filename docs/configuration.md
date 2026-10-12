# Configuration

Every setting comes from one `.env` file at the repo root, copied from `.env.example`. `sh scripts/setup.sh` writes it with the three secrets generated, asking for (or, without a terminal, naming) each missing required value and keeping every value already there; `--help` lists its flags. Every service reads it: the dev stack in `compose.dev.yml` passes it to the backend and the publisher, and the Vite dev server reads it from the repo root.

Only the settings under [Required](#required) must be set. Everything else is optional: leave it unset or empty and the app boots with the default shown, or with that provider off.

Each optional provider is a group of settings (ADR 0011). With all of a group's required settings set, the provider is on; with none set, it is off; with only some set, the backend refuses to start and names the missing ones. The groups are Stripe billing (`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `BILLING_PLAN_KEYS`), Google sign-in (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`), SMTP (`SMTP_HOST`, `EMAIL_FROM`), Operator details (`OPERATOR_NAME`, `OPERATOR_ADDRESS`) and PostHog (`POSTHOG_PROJECT_API_KEY`). `SUPPORT_EMAIL` stands alone, except that Operator details need it: the company footer they turn on gives it as the contact address, so the backend refuses to start with Operator details and no `SUPPORT_EMAIL`.

## Required

| Variable | Meaning |
| --- | --- |
| `PUBLIC_URL` | The origin Users open, such as `https://pumpkit.example.org` or `http://localhost:8080`: a scheme, a host and an optional port, with no path. It serves the frontend and, under `/api`, the API. Every other URL derives from it (see below). The dev stack sets it to `http://localhost:5173` itself. |
| `POSTGRES_PASSWORD` | Database password: a random string of at least 32 characters (`openssl rand -hex 32`). |
| `JWT_SECRET_KEY` | Random string of at least 32 characters used to sign tokens (`openssl rand -hex 32`). |
| `FERNET_ENCRYPTION_KEY` | 32 url-safe base64-encoded bytes that encrypt stored X tokens (`openssl rand -base64 32 \| tr '+/' '-_'`). Changing it makes the stored tokens unreadable. |
| `LLM_API_KEY` | Key for the LLM endpoint, which writes every Post. The backend boots without it, but writing a Post then fails with a 503 naming the variable. |
| `TWITTERAPI_IO_API_KEY` | Reads Inspiration authors' posts from twitterapi.io (ADR 0005). The backend boots without it, but adding an author then fails with a 503 naming the variable. |

## URLs derived from `PUBLIC_URL`

None of these is a setting. A trailing slash on `PUBLIC_URL` is dropped.

| URL | Value | Where it is used |
| --- | --- | --- |
| Frontend | `PUBLIC_URL` | Redirects back to the app after sign-in. |
| API | `PUBLIC_URL/api/v1` | The frontend calls it on its own origin; Magic links point at `PUBLIC_URL/api/v1/login/magic-link`. |
| CORS origins | `PUBLIC_URL` | The only origin allowed to call the API from a browser. |
| Google redirect URI | `PUBLIC_URL/api/v1/oauth/google/callback` | Register it on the Google OAuth client. |
| X redirect URI | `PUBLIC_URL/oauth/x/callback` | Register it as a callback URL on the X app. |
| Stripe Checkout return | `PUBLIC_URL/billing/success` and `PUBLIC_URL/billing/cancelled` | Where Checkout returns after paying or cancelling. |
| Stripe customer portal return | `PUBLIC_URL/billing` | Where the customer portal returns. |
| Stripe webhook | `PUBLIC_URL/api/v1/stripe/webhook` | Register it as the webhook endpoint in Stripe. |
| Canonical and social URLs | `PUBLIC_URL/` | The web container writes them into `index.html`'s canonical, Open Graph, Twitter card and JSON-LD tags, and into `sitemap.xml`, when it starts. |

The scheme of `PUBLIC_URL` also decides the sign-in cookies. With `https` they are `Secure`, and the refresh cookie is named `__Host-refresh_token`; with `http` they are plain and the refresh cookie is `refresh_token`, because Safari drops `Secure` cookies on `http://localhost`.

## Optional

### Release and web server

Read by Docker Compose and the `web` service of the production stack (`compose.yml`); the dev stack ignores them. [self-hosting.md](self-hosting.md) shows the values for a laptop and a server.

| Variable | Meaning |
| --- | --- |
| `PUMPKIT_VERSION` | The release to run: the tag of `ghcr.io/pumpkit-io/pumpkit-backend` and `ghcr.io/pumpkit-io/pumpkit-web`, without the `v` (such as `0.1.0`). `.env.example` sets the current release; change it only to upgrade, after reading `CHANGELOG.md`. With `docker compose up --build`, the images built from the checkout get this tag. |
| `HTTP_PORT` | The host port the web server's plain HTTP listens on. Defaults to 8080, for a laptop. A server with an `https` `PUBLIC_URL` needs 80, where the certificate authority checks the domain and where HTTP redirects to HTTPS. |
| `HTTPS_PORT` | The host port for HTTPS. Defaults to 443. |
| `ACME_EMAIL` | The address the certificate authority sends expiry notices to, for an `https` `PUBLIC_URL`. Optional. |

An `http` `PUBLIC_URL` is served as plain HTTP on any host name; an `https` one gets a certificate for its host automatically, and the web server redirects HTTP to HTTPS.

### LLM endpoint

| Variable | Meaning |
| --- | --- |
| `LLM_BASE_URL` | Any OpenAI-compatible chat completions endpoint, such as `https://api.openai.com/v1` or a local Ollama at `http://localhost:11434/v1`. Defaults to OpenRouter (`https://openrouter.ai/api/v1`). Prompt cache hints are sent only to OpenRouter. |
| `LLM_DRAFTING_MODEL`, `LLM_HUMANIZING_MODEL`, `LLM_REVISING_MODEL` | The model for each writing call: the draft call, the humanizer call, and the revision call after Feedback. Each defaults to `openai/gpt-5.6-luna`, the OpenRouter model the prompts were tuned against; on another endpoint, set all three to models it serves. |

### SMTP

| Variable | Meaning |
| --- | --- |
| `SMTP_HOST`, `EMAIL_FROM` | SMTP server and the address Magic link emails come from. Set both or neither. Without them each Magic link, its recipient and expiry are written to the backend log at warning level, and startup says so; configure SMTP before inviting anyone else. |
| `SMTP_SECURITY` | `starttls` (default), `tls` or `none`. |
| `SMTP_PORT` | Defaults to the security mode's port: 587 for `starttls`, 465 for `tls`, 25 for `none`. |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | SMTP login; leave empty for a server that needs none. |

To send Magic links through Resend, set `SMTP_HOST=smtp.resend.com`, `SMTP_USERNAME=resend`, `SMTP_PASSWORD` to a Resend API key and `EMAIL_FROM` to an address on a domain verified in Resend; the default `starttls` on port 587 works.

### Sign-up allowlist

| Variable | Meaning |
| --- | --- |
| `SIGN_UP_ALLOWLIST` | The Sign-up allowlist: comma-separated email addresses and `@domain` entries (e.g. `me@example.com,@team.example`), matched ignoring case. Checked when a Magic link is requested or completed and when Google sign-in completes; an open Session keeps refreshing until it expires, so Suspend a User to cut them off at once. Empty lets anyone sign in. |

### Google sign-in

| Variable | Meaning |
| --- | --- |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth credentials. Set both or neither. With neither, the sign-in page offers only the Magic link and the Google sign-in routes answer 404. Register `PUBLIC_URL/api/v1/oauth/google/callback` as the client's redirect URI. |

### X app

| Variable | Meaning |
| --- | --- |
| `X_CLIENT_ID` | OAuth 2.0 client id of the X developer app that publishes Scheduled posts (ADR 0006). The app boots without the X settings; connecting an X account then fails with a 503 naming them. Register `PUBLIC_URL/oauth/x/callback` as a callback URL on the X app. |
| `X_CLIENT_SECRET` | That X app's client secret. Pumpkit calls X as a confidential client. |
| `PUBLISHER_POLL_INTERVAL_SECONDS` | How often the publisher process looks for due Scheduled posts. Defaults to 30, so a Scheduled post goes out within about 30 seconds of its time. |
| `SCHEDULED_POSTS_MONTHLY_CAP` | Most Scheduled posts a User may have whose publish time falls in one UTC calendar month, counting Published, waiting and Failed ones (a cancelled one frees its place). Creating, Post now or rescheduling into a full month is refused with the date the cap resets. Defaults to 100. It bounds what the Instance's X app pays for publishing (ADR 0006). Set it empty for no cap, when you pay for your own X app; `0` turns scheduling off. |

### Stripe billing

| Variable | Meaning |
| --- | --- |
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` | Stripe API keys. Part of the Stripe billing group. |
| `STRIPE_WEBHOOK_SECRET` | Signing secret of the webhook endpoint at `PUBLIC_URL/api/v1/stripe/webhook`. Part of the Stripe billing group. |
| `BILLING_PLAN_KEYS` | Part of the Stripe billing group; an empty list counts as unset. The Plans Pumpkit sells: Stripe price lookup keys as a single-quoted JSON list (`'["pumpkit_pro_monthly"]'`), in display order. Only these are listed and purchasable; each must be an active recurring price. `docker compose` `env_file` accepts the quoted form; a plain `docker run --env-file` would keep the quotes as part of the value. |
| `BILLING_TRIAL_PERIOD_DAYS` | Length in days of the Trial a User's first Subscription starts with. Checkout adds it only for a User who has never had a Subscription; the card is collected up front. Defaults to 14. `0` turns Trials off. |

### Support address and Operator details

| Variable | Meaning |
| --- | --- |
| `SUPPORT_EMAIL` | The address the support link opens a new email to. With it, the Magic link sent page offers "Contact support" and the footer shows the address. Without it, both are hidden and `/support/contact` answers 404. Required when the Operator details are set. |
| `OPERATOR_NAME`, `OPERATOR_ADDRESS` | The Operator details group: the company running the Instance. Set both or neither, and set `SUPPORT_EMAIL` with them. With them, the frontend shows the company details in the footer, the Terms and Privacy Policy pages and the sign-in Terms notice, and checkout requires accepting the Terms when the Instance sells Plans (ADR 0011). Without them, none of that appears. |
| `OPERATOR_VAT_ID`, `OPERATOR_REA`, `OPERATOR_SHARE_CAPITAL`, `OPERATOR_PEC` | Company identifiers shown in the footer when the Operator details are set. |

### PostHog

| Variable | Meaning |
| --- | --- |
| `POSTHOG_PROJECT_API_KEY` | PostHog project key. With it set, the frontend loads PostHog after Analytics consent (ADR 0009) and shows the consent banner; without it, neither. |
| `POSTHOG_ENABLED` | `true` to enable server-side analytics and error tracking, given `POSTHOG_PROJECT_API_KEY`. The browser's analytics follow the key alone. Defaults to `false`. |
| `POSTHOG_PERSONAL_API_KEY` | Personal key passed to the backend's PostHog client, which needs it only to evaluate feature flags locally. Pumpkit reads no feature flags, so it can stay unset. |
| `POSTHOG_HOST` | PostHog ingestion host, for the backend and the browser. Defaults to `https://eu.i.posthog.com`. With `POSTHOG_RELAY=true`, set it to the relay path, `PUBLIC_URL/ph-relay` (for example `https://pumpkit.example.org/ph-relay`). |
| `POSTHOG_RELAY` | `true` to have the web server relay PostHog on the Instance's own origin, so adblockers that block PostHog's hosts let analytics through. It proxies `/ph-relay/static/*` to `https://eu-assets.i.posthog.com` and the rest of `/ph-relay/*` to `https://eu.i.posthog.com`, PostHog's EU Cloud. Point `POSTHOG_HOST` at it. Defaults to `false`, which leaves `/ph-relay` an ordinary app route. Read by the `web` service only. |
| `POSTHOG_UI_HOST` | PostHog app host the browser links to when `POSTHOG_HOST` is a relay. Defaults to `https://eu.posthog.com`. |

### Database

The defaults reach the compose stack's bundled Postgres; set these only for an external one, together with `COMPOSE_FILE=compose.yml:compose.external-db.yml`, which leaves the bundled `db` service out of every `docker compose` command ([External Postgres](self-hosting.md#external-postgres)). The backend builds its sync database URL (used by Alembic) with the `psycopg2` driver explicitly and the async one with `asyncpg`.

| Variable | Meaning |
| --- | --- |
| `POSTGRES_USER` | Defaults to `postgres`. |
| `POSTGRES_HOST` | Defaults to `db`, the bundled service. The dev stack always uses `db`. |
| `POSTGRES_PORT` | Defaults to `5432`. |
| `POSTGRES_DB` | Defaults to `postgres`. |
| `POSTGRES_SSL` | `disable` (default) or `require`. With `require` the backend and Alembic connect with SSL (`sslmode=require` / `ssl=require`), which managed Postgres providers need. `ENV` has no effect on SSL. |

### Search indexing

| Variable | Meaning |
| --- | --- |
| `ALLOW_SEARCH_INDEXING` | `false` (default) or `true`, read by the web container when it starts. `false` serves `index.html` with `<meta name="robots" content="noindex,nofollow">` and a `robots.txt` that disallows every path, so the Instance stays out of search engines. `true` serves `index,follow` and a `robots.txt` that allows crawling (except `/home` and `/billing`) and names `PUBLIC_URL/sitemap.xml`. The hosted Instance at pumpkit.io sets `true`. |

### Instance and internal tunables

These rarely need changing. `.env.example` lists only `APP_NAME` and `LOG_LEVEL`.

| Variable | Meaning |
| --- | --- |
| `APP_NAME` | Brand name used in emails, server-side copy and the UI, which reads it from `GET /api/v1/instance`. Defaults to `Pumpkit`. |
| `LOG_LEVEL` | Python log level. Defaults to `INFO`. |
| `ENV` | `prod` (default) or `local`. It only tags each PostHog event with `env`, so one PostHog project can keep environments apart. The dev stack sets `local`. |
| `JWT_ALGORITHM` | Signing algorithm. Defaults to `HS256`. |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime. Defaults to 30. |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token lifetime. Defaults to 30. |
| `JWT_ISSUER`, `JWT_AUDIENCE` | `iss` / `aud` claims of issued tokens. Default to `pumpkit` and `pumpkit-api`. |
| `COOKIE_MAX_AGE_SECONDS` | Refresh cookie lifetime. Defaults to 2592000 (30 days). |
| `MAGIC_LINK_TOKEN_DURATION_MINUTES`, `MAGIC_LINK_TOKEN_NUM_BYTES` | Magic-link token lifetime and size. Default to 15 and 32. |
| `GOOGLE_NONCE_TOKEN_NUM_BYTES`, `GOOGLE_CODE_VERIFIER_TOKEN_NUM_BYTES` | Size of the OAuth nonce and PKCE verifier. Default to 64. |
| `GOOGLE_COOKIE_MAX_AGE_SECONDS` | Lifetime of the short-lived PKCE/CSRF cookies during OAuth. Defaults to 600. |
| `GOOGLE_TOKEN_ENDPOINT_TIMEOUT_SECONDS` | Timeout for Google's token endpoint. Defaults to 30. |

### Development only

| Variable | Meaning |
| --- | --- |
| `VITE_BYPASS_AUTH` | `true` makes the Vite dev server treat every route as authenticated. Ignored in production builds. |
| `API_PROXY_TARGET` | Where the Vite dev server proxies `/api`. Defaults to `http://localhost:8000`; `compose.dev.yml` sets `http://backend:8000`. Not read from `.env`. |
