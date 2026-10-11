# Configuration

Every setting comes from environment variables, split across three files copied from their `.env.example`: the root `.env`, `backend/.env` and `frontend/.env`.

Variables marked (optional) can be left empty; the app boots without them, using the default shown. Only the Instance's URLs, the database, `JWT_SECRET_KEY`, `FERNET_ENCRYPTION_KEY` and the Resend variables are required.

Each optional provider is a group of settings (ADR 0011). With all of a group's required settings set, the provider is on; with none set, it is off; with only some set, the backend refuses to start and names the missing ones. The groups are Stripe billing (`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `BILLING_PLAN_KEYS`), Google sign-in (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) and PostHog (`POSTHOG_PROJECT_API_KEY`).

## Root `.env`

| Variable | Meaning |
| --- | --- |
| `ENV` | `local` or `prod`. With `prod` the database connection requires SSL. |
| `LOG_LEVEL` (optional) | Python log level. Defaults to `INFO`. |
| `APP_NAME` (optional) | Brand name used in emails and server-side copy. Defaults to `Pumpkit`. |
| `BACKEND_URL`, `BACKEND_PORT` | Public URL and port of the backend. |
| `FRONTEND_URL`, `FRONTEND_PORT` | Public URL and port of the frontend. |
| `CORS_ORIGINS` | Allowed origins, as a quoted JSON list (see note below). |
| `POSTGRES_USER`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` | Database connection parts. |
| `POSTGRES_PASSWORD` | Database password: a random string of at least 32 characters. |

`CORS_ORIGINS` is single-quoted JSON (`'["http://localhost:5173"]'`). `docker compose` `env_file` accepts that form; a plain `docker run --env-file` would keep the quotes as part of the value. The backend builds its sync database URL (used by Alembic) with the `psycopg2` driver explicitly and the async one with `asyncpg`.

## `backend/.env`

| Variable | Meaning |
| --- | --- |
| `JWT_SECRET_KEY` | Random string of at least 32 characters used to sign tokens. |
| `JWT_ALGORITHM` (optional) | Signing algorithm. Defaults to `HS256`. |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (optional) | Access token lifetime. Defaults to 30. |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` (optional) | Refresh token lifetime. Defaults to 30. |
| `JWT_ISSUER`, `JWT_AUDIENCE` (optional) | `iss` / `aud` claims of issued tokens. Default to `pumpkit` and `pumpkit-api`. |
| `COOKIE_MAX_AGE_SECONDS` (optional) | Refresh cookie lifetime. Defaults to 2592000 (30 days). |
| `FERNET_ENCRYPTION_KEY` | 32 url-safe base64-encoded bytes (generate with `Fernet.generate_key()`). |
| `MAGIC_LINK_TOKEN_DURATION_MINUTES`, `MAGIC_LINK_TOKEN_NUM_BYTES` (optional) | Magic-link token lifetime and size. Default to 15 and 32. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (optional) | Google OAuth credentials. Set both or neither. |
| `GOOGLE_OAUTH_REDIRECT_URI` (optional) | Must match the redirect URI registered in Google Cloud. Defaults to `BACKEND_URL` + `/api/v1/oauth/google/callback`. |
| `GOOGLE_NONCE_TOKEN_NUM_BYTES`, `GOOGLE_CODE_VERIFIER_TOKEN_NUM_BYTES` (optional) | Size of the OAuth nonce and PKCE verifier. Default to 64. |
| `GOOGLE_COOKIE_MAX_AGE_SECONDS` (optional) | Lifetime of the short-lived PKCE/CSRF cookies during OAuth. Defaults to 600. |
| `GOOGLE_TOKEN_ENDPOINT_TIMEOUT_SECONDS` (optional) | Timeout for Google's token endpoint. Defaults to 30. |
| `RESEND_API_KEY` | Resend API key for transactional email. |
| `RESEND_NOREPLY_ADDRESS`, `RESEND_SUPPORT_ADDRESS` | Sender and support addresses. |
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY` (optional) | Stripe API keys. Part of the Stripe billing group. |
| `STRIPE_WEBHOOK_SECRET` (optional) | Signing secret of the webhook endpoint. Part of the Stripe billing group. |
| `STRIPE_CHECKOUT_SUCCESS_URL`, `STRIPE_CHECKOUT_CANCEL_URL` (optional) | Where Checkout returns after paying or cancelling. Default to `FRONTEND_URL` + `/billing/success` and `/billing/cancelled`. |
| `STRIPE_BILLING_PORTAL_RETURN_URL` (optional) | Where the customer portal returns. Defaults to `FRONTEND_URL` + `/billing`. |
| `BILLING_PLAN_KEYS` (optional) | Part of the Stripe billing group; an empty list counts as unset. The Plans Pumpkit sells: Stripe price lookup keys as a quoted JSON list (like `CORS_ORIGINS`), in display order. Only these are listed and purchasable; each must be an active recurring price. |
| `BILLING_TRIAL_PERIOD_DAYS` (optional) | Length in days of the Trial a User's first Subscription starts with. Checkout adds it only for a User who has never had a Subscription; the card is collected up front. Defaults to 14. `0` turns Trials off. |
| `OPENROUTER_API_KEY` (optional) | Enables the LLM client; without it calls raise `LLMNotConfiguredError`. |
| `TWITTERAPI_IO_API_KEY` (optional) | Reads Inspiration authors' posts from twitterapi.io (ADR 0005). The app boots without it; adding an author then fails with a 503 naming the variable. |
| `X_CLIENT_ID` (optional) | OAuth 2.0 client id of the X developer app that publishes Scheduled posts (ADR 0006). The app boots without the three X settings; connecting an X account then fails with a 503 naming them. |
| `X_CLIENT_SECRET` (optional) | That X app's client secret. Pumpkit calls X as a confidential client. |
| `X_REDIRECT_URI` (optional) | The frontend's `/oauth/x/callback` route, e.g. `http://localhost:5173/oauth/x/callback`. Register the same URL as a callback on the X app. |
| `PUBLISHER_POLL_INTERVAL_SECONDS` (optional) | How often the publisher process looks for due Scheduled posts. Defaults to 30, so a Scheduled post goes out within about 30 seconds of its time. |
| `SCHEDULED_POSTS_MONTHLY_CAP` (optional) | Most Scheduled posts a User may have whose publish time falls in one UTC calendar month, counting Published, waiting and Failed ones (a cancelled one frees its place). Creating, Post now or rescheduling into a full month is refused with the date the cap resets. Defaults to 100. It bounds what Pumpkit's X app pays for publishing (ADR 0006). `0` turns scheduling off. |
| `POSTHOG_ENABLED` (optional) | `true` to enable server-side analytics and error tracking. |
| `POSTHOG_PROJECT_API_KEY` (optional) | PostHog project key. |
| `POSTHOG_PERSONAL_API_KEY` (optional) | Personal key, used by `scripts/deploy.sh` for deploy annotations. |
| `POSTHOG_HOST` (optional) | PostHog ingestion host. |

## `frontend/.env`

| Variable | Meaning |
| --- | --- |
| `VITE_API_URL` | Backend API base URL, e.g. `http://localhost:8000/api/v1`. Required for builds. |
| `VITE_APP_NAME` | Brand name shown in the UI (default `Pumpkit`). |
| `VITE_BYPASS_AUTH` | Dev only: treat every route as authenticated. Ignored in production builds. |
| `VITE_POSTHOG_ENABLED` (optional) | `true` to enable browser analytics. |
| `VITE_POSTHOG_KEY` (optional) | PostHog project key. |
| `VITE_POSTHOG_HOST` (optional) | Ingestion host; in production point it at your reverse-proxy path (`https://<domain>/ph-relay`). |
| `VITE_POSTHOG_UI_HOST` (optional) | PostHog UI host, used for links. |

