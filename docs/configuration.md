# Configuration

Every setting comes from one `.env` file at the repo root, copied from `.env.example`. `sh scripts/setup.sh` writes it with the three secrets generated, asking for (or, without a terminal, naming) each missing required value and keeping every value already there; `--help` lists its flags. Every service reads it: the dev stack in `compose.dev.yml` passes it to the backend and the publisher, and the Vite dev server reads it from the repo root.

Only the settings under [Required](#required) must be set. Everything else is optional: leave it unset or empty and the app boots with the default shown, or with that provider off.

Each optional provider is a group of settings (ADR 0011). With all of a group's required settings set, the provider is on; with none set, it is off; with only some set, the backend refuses to start and names the missing ones. The groups are Stripe billing (`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `BILLING_PLAN_KEYS`), Google sign-in (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`), SMTP (`SMTP_HOST`, `EMAIL_FROM`), Operator details (`OPERATOR_NAME`) and PostHog (`POSTHOG_PROJECT_API_KEY`). `SUPPORT_EMAIL` stands alone, except that Operator details need it: the company footer they turn on gives it as the contact address, so the backend refuses to start with Operator details and no `SUPPORT_EMAIL`.

## Required

| Variable | Meaning |
| --- | --- |
| `PUBLIC_URL` | The origin Users open, such as `https://pumpkit.example.org` or `http://localhost:8080`: a scheme, a host and an optional port, with no path. It serves the frontend and, under `/api`, the API. Every other URL derives from it (see below). The dev stack sets it to `http://localhost:5173` itself. |
| `POSTGRES_PASSWORD` | Database password: a random string of at least 32 characters (`openssl rand -hex 32`). |
| `JWT_SECRET_KEY` | Random string of at least 32 characters used to sign tokens (`openssl rand -hex 32`). |
| `FERNET_ENCRYPTION_KEY` | 32 url-safe base64-encoded bytes that encrypt stored X tokens (`openssl rand -base64 32 \| tr '+/' '-_'`). Changing it makes the stored tokens unreadable. |
| `LLM_API_KEY` | Key for the LLM endpoint, which writes every Post. The backend boots without it, but writing a Post then fails with a 503 naming the variable. |
| `TWITTERAPI_IO_API_KEY` | Looks up X accounts and reads Inspiration authors' posts from twitterapi.io (ADR 0005), and the names of Communities Users paste. The backend boots without it, but adding an author then fails with a 503 naming the variable, and a pasted Community shows its ID instead of its name. |

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
| MCP endpoint | `PUBLIC_URL/api/v1/mcp` | Claude Code and other MCP clients connect to it with an API key; the `claude mcp add` command in Settings' API keys card names it. |
| Canonical and social URLs | `PUBLIC_URL/` | The web container writes them into `index.html`'s canonical, Open Graph, Twitter card and JSON-LD tags, and into `sitemap.xml`, when it starts. |

The scheme of `PUBLIC_URL` also decides the sign-in cookies. With `https` they are `Secure`, and the refresh cookie is named `__Host-refresh_token`; with `http` they are plain and the refresh cookie is `refresh_token`, because Safari drops `Secure` cookies on `http://localhost`.

## Optional

### Release and web server

Read by Docker Compose and the `web` service of the production stack (`compose.yml`); the dev stack ignores them. [self-hosting.md](self-hosting.md) shows the values for a laptop and a server.

| Variable | Meaning |
| --- | --- |
| `PUMPKIT_VERSION` | The release to run: the tag of `ghcr.io/pumpkit-io/pumpkit-backend` and `ghcr.io/pumpkit-io/pumpkit-web`, without the `v` (such as `0.1.0`). `.env.example` sets the current release; change it only to upgrade, after reading `CHANGELOG.md`. With `docker compose up --build`, the images built from the checkout get this tag. |
| `HTTP_PORT` | The host port the web server's plain HTTP listens on. Defaults to 8080, for a laptop. A server with an `https` `PUBLIC_URL` needs 80, which redirects HTTP to HTTPS and answers the certificate authority's HTTP-01 challenge. |
| `HTTPS_PORT` | The host port for HTTPS. Defaults to 443. |
| `ACME_EMAIL` | The address the certificate authority sends expiry notices to, for an `https` `PUBLIC_URL`. Optional. |
| `TRUSTED_PROXIES` | Addresses or CIDR ranges of a proxy in front of the web server, separated by spaces (such as `203.0.113.10 10.1.0.0/16`). The web server then keeps the caller address that proxy forwards instead of replacing it, so per-IP rate limits see each caller. Leave it unset when nothing sits in front. See [self-hosting.md](self-hosting.md#a-proxy-in-front-of-the-web-server). |
| `FORWARDED_ALLOW_IPS` | Addresses or CIDR ranges the backend trusts `X-Forwarded-For` from, separated by commas. Defaults to `127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`, and a value replaces the default. Set it when a proxy with a public address sits in front of the web server, adding that address. Never `*` while the backend's port is reachable from outside the compose network. Read by the `backend`, so it lives in the same `.env`. See [self-hosting.md](self-hosting.md#a-proxy-in-front-of-the-web-server). |

An `http` `PUBLIC_URL` is served as plain HTTP on any host name; an `https` one gets a certificate for its host automatically, and the web server redirects HTTP to HTTPS.

### LLM endpoint

| Variable | Meaning |
| --- | --- |
| `LLM_BASE_URL` | Any OpenAI-compatible chat completions endpoint, such as `https://api.openai.com/v1` or a local Ollama at `http://localhost:11434/v1`. Defaults to OpenRouter (`https://openrouter.ai/api/v1`). Prompt cache hints are sent only to OpenRouter. |
| `LLM_SKETCHING_MODEL`, `LLM_HUMANIZING_MODEL`, `LLM_REVISING_MODEL` | The model for each writing call: the sketch call, the humanizer call, and the revision call after Feedback. Each defaults to `openai/gpt-5.6-luna`, the OpenRouter model the prompts were tuned against; on another endpoint, set all three to models it serves. |

### Author lookups

Adding an Inspiration author whose handle isn't in the Author directory first looks its profile up on twitterapi.io (ADR 0019). An account found and public joins the directory for good; a missing, suspended or private one is remembered for every User. Picking from the directory and answering from a remembered miss never count towards a limit, and nor does refreshing an author's posts, which keeps its cooldown of a day per handle. Over a User's limit, adding answers 429 with the minutes until the oldest counted lookup leaves the hour or the day; over the Instance's cap, it answers that lookups are paused for today.

| Variable | Meaning |
| --- | --- |
| `AUTHOR_LOOKUP_HOURLY_LIMIT`, `AUTHOR_LOOKUP_DAILY_LIMIT` | Lookups each User may run in any hour and in any 24 hours. Default to 10 and 30. |
| `AUTHOR_LOOKUP_INSTANCE_DAILY_LIMIT` | Lookups the whole Instance may run in any 24 hours, a ceiling on twitterapi.io spend. Defaults to 500. |
| `AUTHOR_MISS_DAYS` | Days a handle that isn't on X, or is suspended, answers "@handle isn't on X" without a lookup. Defaults to 7. |
| `AUTHOR_PRIVATE_MISS_DAYS` | Days a private account answers that it's private without a lookup. Defaults to 1, so it can be added soon after it goes public. |
| `AUTHOR_POSTS_REUSE_DAYS` | Adding an author reuses posts any User fetched within this many days instead of fetching them again, and a fetch that found no posts answers that the account has none for as long. Defaults to 7. |

Each fetch of an author's posts updates its directory entry's photo, and its name too, except for a seeded account, which keeps the name it was seeded with.

### SMTP

| Variable | Meaning |
| --- | --- |
| `SMTP_HOST`, `EMAIL_FROM` | SMTP server and the address Magic link emails come from. Set both or neither. Without them each Magic link, its recipient and expiry are written to the backend log at warning level, and startup says so; configure SMTP before inviting anyone else. |
| `SMTP_SECURITY` | `starttls` (default), `tls` or `none`. |
| `SMTP_PORT` | Defaults to the security mode's port: 587 for `starttls`, 465 for `tls`, 25 for `none`. Some cloud providers, DigitalOcean among them, block those ports going out; see [No Magic link arrives](self-hosting.md#troubleshooting). |
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

### Gravatar

| Variable | Meaning |
| --- | --- |
| `GRAVATAR_ENABLED` | `true` to fill an empty Photo from Gravatar when a User signs in with a Magic link, for a User who has never saved or removed a Photo. Pumpkit sends Gravatar (Automattic) a SHA-256 hash of the email address and stores a copy of the picture; an email with no Gravatar keeps its initials. Defaults to `false`, so nothing about Users' email addresses leaves the Instance. If you turn it on, say so in your privacy notice. |

### X app

| Variable | Meaning |
| --- | --- |
| `X_CLIENT_ID` | OAuth 2.0 client id of the X developer app that publishes Scheduled posts (ADR 0006). The app boots without the X settings; Onboarding then skips its X step, the web app offers no way to connect X, and the API's authorization route answers a 503 naming them. Register `PUBLIC_URL/oauth/x/callback` as a callback URL on the X app. |
| `X_CLIENT_SECRET` | That X app's client secret. Pumpkit calls X as a confidential client. |
| `PUBLISHER_ENABLED` | `false` keeps the publisher process running without publishing anything, so Scheduled posts wait until it is `true` again. Defaults to `true`. `scripts/dev-stack` sets it to `false` for each development copy of the app, which may share an `.env` holding real X credentials. |
| `PUBLISHER_POLL_INTERVAL_SECONDS` | How often the publisher process looks for due Scheduled posts. Defaults to 30, so a Scheduled post goes out within about 30 seconds of its time. |
| `X_POSTS_MONTHLY_CAP` | Most X posts a User may have whose publish time falls in one period, counting the Parts of Published and waiting Scheduled posts and the Parts of Failed ones that X accepted: a single post is one X post, a Thread one per Part (a cancelled one, or a Part X never accepted, frees its place). On an Instance that sells Plans the period is the Allowance period, as for `GENERATIONS_MONTHLY_CAP`, and a Trial gets a quarter, rounded down; on one that sells none it is the UTC calendar month. Creating, Post now, rescheduling or adding Parts that would go over is refused with the date the count resets, and a Thread that doesn't fit is refused whole. Defaults to 100. It bounds what the Instance's X app pays for publishing (ADR 0006). Set it empty for no cap, when you pay for your own X app; `0` turns scheduling off. |
| `X_LINK_POSTS_MONTHLY_CAP` | How many of those X posts may contain a link, counted the same way: a Part counts when X would turn something in it into a link, a bare domain such as `pumpkit.io` too. X charges far more for an X post with a link. Defaults to 10 (a Trial gets 2). Set it empty for no cap. |

### Stripe billing

| Variable | Meaning |
| --- | --- |
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` | Stripe API keys. Part of the Stripe billing group. |
| `STRIPE_WEBHOOK_SECRET` | Signing secret of the webhook endpoint at `PUBLIC_URL/api/v1/stripe/webhook`. Part of the Stripe billing group. |
| `BILLING_PLAN_KEYS` | Part of the Stripe billing group; an empty list counts as unset. The Plans Pumpkit sells: Stripe price lookup keys as a single-quoted JSON list (`'["pumpkit_pro_monthly"]'`), in display order. Only these are listed and purchasable; each must be an active recurring price. `docker compose` `env_file` accepts the quoted form; a plain `docker run --env-file` would keep the quotes as part of the value. |
| `BILLING_TRIAL_PERIOD_DAYS` | Length in days of the Trial a User's first Subscription starts with. Checkout adds it only for a User who has never had a Subscription; the card is collected up front. Defaults to 7. `0` turns Trials off. |
| `GENERATIONS_MONTHLY_CAP` | Generations in a Subscribed User's Allowance: how many Versions Pumpkit may write for them per Allowance period, starting a Post and each Feedback counting one and failed attempts none. An Allowance period starts each month on the day and time the Subscription's paid periods started (the last day of a shorter month when that day is missing), on annual Plans too; a Trial is one period with a quarter of the cap, rounded down. Starting a Post or giving Feedback with none left is refused with the date they reset. Defaults to 500. Applies only on an Instance that sells Plans; set it empty for no cap. |
| `BILLING_TOP_UP_KEY` | The Stripe lookup key of the Top-up's one-off price, VAT-inclusive (€10 on pumpkit.io). It needs the Stripe billing group; without it the Instance sells no Top-ups and no limit message offers one. A Top-up adds half of each cap, rounded down (250 generations and 50 X posts, up to 5 with a link, at the defaults), lasts 12 months from purchase and is spent only once the Allowance is used up, starting with the one that expires first. Only a User on a paid-up paid Subscription may buy one: not during a Trial, and not while behind on payment. It is added when Stripe's webhook reports the payment, and a refund or dispute removes what is left of it: what it already paid for, waiting Scheduled posts included, stays paid for and doesn't count against the Allowance. |

### Support address and Operator details

| Variable | Meaning |
| --- | --- |
| `SUPPORT_EMAIL` | The address the support link opens a new email to. With it, the Magic link sent page offers "Contact support" and the footer shows the address. Without it, both are hidden and `/support/contact` answers 404. Required when the Operator details are set. |
| `OPERATOR_NAME` | The Operator details group: the company running the Instance. Set `SUPPORT_EMAIL` with it. With it, the frontend shows the company line and the Company details link in the footer, the Terms and Privacy Policy pages and the sign-in Terms notice, and checkout requires accepting the Terms when the Instance sells Plans (ADR 0011). Without it, none of that appears. |
| `OPERATOR_VAT_ID` | The VAT ID shown after the company name in the footer when the Operator details are set. |

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
| `ALLOW_SEARCH_INDEXING` | `false` (default) or `true`, read by the web container when it starts. `false` serves `index.html` with `<meta name="robots" content="noindex,nofollow">` and a `robots.txt` that disallows every path, so the Instance stays out of search engines. `true` serves `index,follow` and a `robots.txt` that allows crawling (except the signed-in pages and `/billing`) and names `PUBLIC_URL/sitemap.xml`. The hosted Instance at pumpkit.io sets `true`. |

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
