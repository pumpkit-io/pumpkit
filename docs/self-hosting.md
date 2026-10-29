# Self-hosting Pumpkit

This guide runs your own Instance of Pumpkit with Docker Compose, on your computer or on a server. It is the source of truth for the prompt in the README: an agent following that prompt follows this guide.

Every step is a command, then a **Check** with its expected output. Run the check before moving on. When a check fails, stop and look the symptom up in [Troubleshooting](#troubleshooting).

## For agents

Run the [install](#install) steps in order, with these rules:

1. Before changing anything, ask whether to run Pumpkit on this computer (the laptop path) or on a server reachable over SSH (the server path). For a server, also ask for the SSH host and the domain name. On the server path, run every command on the server, in the clone, with `ssh <host> '<command>'`, except where a step says to run it on this computer.
2. Ask for provider keys one provider at a time, in the order of [Providers](#providers). For each, tell the Self-hoster where to get the key, link its pricing page (the guide gives no prices, because they change), and say what stops working without it. The two required providers come first; for each optional one, ask whether they want it and skip it when they don't.
3. Pass keys to `scripts/setup.sh` as environment variables, never as flags, and never print `.env` or a key. `.env` is git-ignored; leave it uncommitted.
4. When you finish, run the [health check](#5-check-the-health-endpoint), then tell the Self-hoster the URL to open and how to sign in ([step 6](#6-sign-in)). If SMTP is not configured, tell them Magic links are in the backend log until they [configure SMTP](#7-configure-smtp-before-inviting-anyone).

## Install

### 1. Check the prerequisites

You need Docker with Compose v2, git and openssl (macOS and most Linux distributions include it). On a laptop, install [Docker Desktop](https://docs.docker.com/desktop/); on a Linux server, [Docker Engine](https://docs.docker.com/engine/install/) with its Compose plugin, and run Docker as root or as a user in the `docker` group.

```sh
docker compose version
git --version
openssl version
```

**Check:** the first line reads `Docker Compose version v2.` followed by the rest of the version (for example `Docker Compose version v2.31.0`); the second reads `git version` and a version; the third reads `OpenSSL` or `LibreSSL` and a version.

**Server path only.** Point the domain at the server with an `A` record (and an `AAAA` record if the server has IPv6), and open ports 80 and 443 in the server's firewall and in the cloud provider's firewall. Caddy, inside the web container, serves Pumpkit on 443 and redirects HTTP to HTTPS on 80; it gets its certificate through either port. On this computer:

```sh
dig +short pumpkit.example.org
```

**Check:** it prints the server's public IP address, the one the hosting provider shows for it.

### 2. Get the code

```sh
git clone https://github.com/pumpkit-io/pumpkit.git
cd pumpkit
git checkout "$(git describe --tags --abbrev=0)"
ls compose.yml .env.example
```

The `git checkout` moves to the latest release, so the compose file, `setup.sh` and this guide match the release images that `.env` pins. `main` can be ahead of them.

**Check:** `git describe --tags` prints a release tag such as `v0.1.0`, and `ls` prints `.env.example` and `compose.yml`. If the folder is already a clone, skip `git clone`, run `git fetch --tags`, and run the rest inside it.

### 3. Write `.env`

`scripts/setup.sh` writes `.env` from `.env.example`, generates the database password and the two secrets, and sets the file's mode to 600. It never prints a secret, and on a second run it keeps every value already in `.env`. Get the two required keys first: [LLM endpoint](#llm-endpoint-required) and [twitterapi.io](#twitterapiio-required).

Choose `PUBLIC_URL`, the address Users open:

| Path | `PUBLIC_URL` | Also pass |
| --- | --- | --- |
| Laptop | `http://localhost:8080` | nothing; with port 8080 taken, `--http-port 8081` and `--public-url http://localhost:8081` |
| Server | `https://pumpkit.example.org`, your domain | `--http-port 80`, and optionally `--acme-email you@example.org` for certificate expiry notices |

`PUBLIC_URL` must be an address the clients can reach, not only the browser: Claude Code and other MCP clients connect to `PUBLIC_URL/api/v1/mcp` (see [docs/claude-code.md](claude-code.md)), so a laptop's `http://localhost:8080` works only for clients on that laptop.

An `https://` `PUBLIC_URL` gets a certificate automatically; an `http://` one is served as plain HTTP on any host. The web container listens on `HTTP_PORT` (default 8080, for laptops) and `HTTPS_PORT` (default 443). A server needs `HTTP_PORT=80`: port 80 serves the redirect from HTTP to HTTPS and answers the certificate authority's HTTP-01 challenge.

Laptop:

```sh
LLM_API_KEY='<your LLM key>' TWITTERAPI_IO_API_KEY='<your twitterapi.io key>' \
  sh scripts/setup.sh --public-url http://localhost:8080 </dev/null
```

Server:

```sh
LLM_API_KEY='<your LLM key>' TWITTERAPI_IO_API_KEY='<your twitterapi.io key>' \
  sh scripts/setup.sh --public-url https://pumpkit.example.org --http-port 80 </dev/null
```

To add optional providers now, put their settings in the same command as environment variables (each provider below names them); you can also add them later with [Add or change a setting](#add-or-change-a-setting). In a terminal, `sh scripts/setup.sh` with no arguments asks for each missing required value instead.

**Check:** the output is:

```
Wrote /path/to/pumpkit/.env (mode 600).
Generated: POSTGRES_PASSWORD JWT_SECRET_KEY FERNET_ENCRYPTION_KEY
Set: PUBLIC_URL LLM_API_KEY TWITTERAPI_IO_API_KEY
Next, start Pumpkit:
  docker compose up -d --wait
```

The `Set:` line also names any optional setting you passed. If it instead starts with `Missing required values:`, it names each value to pass and writes nothing.

### 4. Start Pumpkit

```sh
docker compose up -d --wait
```

It pulls the release images named by `PUMPKIT_VERSION` in `.env`, starts Postgres, the backend (which applies database migrations first), the publisher and the web server, and returns once each is healthy. The first start takes a minute or two.

**Check:** the command exits 0 and its last lines read `Healthy`. Then:

```sh
docker compose ps --format 'table {{.Service}}\t{{.Status}}'
```

prints four services, each `Up` and `(healthy)`:

```
SERVICE     STATUS
backend     Up 15 seconds (healthy)
db          Up 26 seconds (healthy)
publisher   Up 9 seconds (healthy)
web         Up 14 seconds (healthy)
```

With an [external Postgres](#external-postgres), `db` is not listed.

### 5. Check the health endpoint

Laptop path, with your `PUBLIC_URL`:

```sh
curl -s http://localhost:8080/api/v1/health
```

Server path, on this computer, with your `PUBLIC_URL`:

```sh
curl -s https://pumpkit.example.org/api/v1/health
```

**Check:** it prints `{"status":"ok"}`. `{"status":"unavailable"}` means the backend cannot reach the database.

**Server path only**, on this computer:

```sh
curl -sI http://pumpkit.example.org/ | head -1
```

**Check:** it prints `HTTP/1.1 308 Permanent Redirect`: port 80 is open and redirects to HTTPS.

### 6. Sign in

Open `PUBLIC_URL` in a browser, choose **Get started**, enter your email address and send the Magic link. Without SMTP, the backend writes the Magic link to its log instead of emailing it:

```sh
docker compose logs backend | grep "Magic link for"
```

**Check:** it prints a line like this, with your address and a token:

```
backend-1  | [2026-10-12 08:24:55] [mailer.py:send_magic_link:130] [WARNING] Magic link for you@example.com (expires in 15 minutes): http://localhost:8080/api/v1/login/magic-link?token=...
```

Open that URL in the same browser within 15 minutes. **Check:** the browser lands on `PUBLIC_URL/new`, the **New post** page, which shows your address in the sidebar.

To write a first Post, add an X handle on the **Persona** page, then type a Brief on **New post** and choose **Write the Post**. **Check:** after a minute or two a Version appears.

### 7. Configure SMTP before inviting anyone

Magic links in the log are fine for you alone. Anyone else can only sign in by email, so [configure SMTP](#smtp) before you invite anyone, and set a [Sign-up allowlist](#sign-up-allowlist) if only some people may sign in.

## Providers

Pumpkit needs two providers. Every other one is optional: with none of its settings, it is off and the rest of Pumpkit works without it. With only some of a provider's settings, the backend refuses to start and names the missing ones. [`docs/configuration.md`](configuration.md) describes every setting.

### LLM endpoint (required)

Writes every Post. Pumpkit calls any OpenAI-compatible endpoint, [OpenRouter](https://openrouter.ai) by default.

- Get a key: [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys).
- Pricing: [OpenRouter pricing](https://openrouter.ai/pricing); Pumpkit's default model is [`openai/gpt-5.6-luna`](https://openrouter.ai/openai/gpt-5.6-luna), whose page lists its price per token. Each Version makes two model calls.
- Settings: `LLM_API_KEY`. For another endpoint, also set `LLM_BASE_URL` and the three models it serves: `LLM_SKETCHING_MODEL`, `LLM_HUMANIZING_MODEL` and `LLM_REVISING_MODEL`.
- Without it: `scripts/setup.sh` refuses to write `.env`. With a wrong key, writing a Post fails.
- **Check:** a Post you write gets a Version ([step 6](#6-sign-in)).

### twitterapi.io (required)

Reads the recent posts of each Inspiration author, which set the style Pumpkit writes in (ADR 0005), and the name of each Community a User pastes to post into.

- Get a key: sign up at [twitterapi.io](https://twitterapi.io/dashboard); the key is on the dashboard.
- Pricing: [twitterapi.io pricing](https://twitterapi.io/pricing).
- Settings: `TWITTERAPI_IO_API_KEY`.
- Without it: `scripts/setup.sh` refuses to write `.env`. With a wrong key, adding an Inspiration author fails, and a User with no Inspiration author cannot write a Post. A pasted Community shows its ID instead of its name, and posting into it still works.
- **Check:** adding an X handle on the **Persona** page lists it.

### SMTP

Emails Magic links. Any SMTP server works; [Resend](https://resend.com/docs/send-with-smtp) is one.

- Get credentials from your email provider. For Resend: verify a sending domain, create an API key, and use host `smtp.resend.com`, username `resend` and the API key as password.
- Pricing: your provider's; Resend's is at [resend.com/pricing](https://resend.com/pricing).
- Settings: `SMTP_HOST` and `EMAIL_FROM` (an address on your verified domain), plus `SMTP_USERNAME` and `SMTP_PASSWORD`. `SMTP_SECURITY` is `starttls` (default, port 587), `tls` (465) or `none` (25); `SMTP_PORT` overrides the port.
- Without it: Magic links go to the backend log, so only someone who can read the log can sign in.

```sh
SMTP_HOST=smtp.resend.com EMAIL_FROM=pumpkit@example.org SMTP_USERNAME=resend SMTP_PASSWORD='<your Resend API key>' \
  sh scripts/setup.sh </dev/null
docker compose up -d --wait
docker compose logs backend | grep -c "SMTP is not configured"
```

**Check:** the last command prints `0`. Then request a Magic link for your own address: it arrives by email, and `docker compose logs backend | grep "Magic link for"` prints nothing new.

### Sign-up allowlist

Not a provider, but set it before you share the address if only some people may sign in.

- Settings: `SIGN_UP_ALLOWLIST`, comma-separated addresses and `@domain` entries, such as `me@example.org,@team.example.org`.
- Without it: anyone who can reach the Instance can sign in.
- **Check:** asking for a Magic link for an address outside the list shows "This site doesn't accept sign-ins from that email address." on the sign-in page.

### Google sign-in

Adds "Continue with Google" to the sign-in page.

- Get credentials: in the [Google Cloud console](https://console.cloud.google.com/apis/credentials), configure the OAuth consent screen, then create an OAuth client ID of type **Web application** and register this redirect URI: `PUBLIC_URL/api/v1/oauth/google/callback` (for example `https://pumpkit.example.org/api/v1/oauth/google/callback`).
- Pricing: Google sign-in has no charge.
- Settings: `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
- Without it: Users sign in with a Magic link only.

```sh
curl -s http://localhost:8080/api/v1/instance | grep -o '"sign_in_methods":[^]]*]'
```

**Check** (with your `PUBLIC_URL` in place of `http://localhost:8080`): it prints `"sign_in_methods":["magic_link","google"]`.

### X app

Lets Users connect their X account, then schedule their Posts or post them now (ADR 0006). Your X app pays for every publish.

- Get credentials: in the [X developer portal](https://developer.x.com/en/portal/dashboard), create an app and set up its user authentication: OAuth 2.0, app type **Web App, Automated App or Bot** (a confidential client), permissions **Read and write**. Register this callback URL: `PUBLIC_URL/oauth/x/callback` (for example `https://pumpkit.example.org/oauth/x/callback`), and use `PUBLIC_URL` as the website URL. Copy the OAuth 2.0 client ID and client secret.
- Pricing: [X API pricing](https://docs.x.com/x-api/getting-started/pricing). `X_POSTS_MONTHLY_CAP` (default 100 X posts per User per month, each Part of a Thread counting as one) bounds what each User can cost you; set it empty for no cap.
- Settings: `X_CLIENT_ID` and `X_CLIENT_SECRET`.
- Without it: connecting an X account fails, so nobody can schedule or publish to X. Writing Posts still works; Users copy a Version's text instead.
- **Check:** on the **Posts** page, connecting X sends you to X to authorise the app and back to the Posts page, connected.

### Stripe billing

Sells Plans. Without it the Instance sells no Plans and every signed-in User may use all of Pumpkit. See [Selling Plans](#selling-plans) for the whole setup.

- Get keys: [dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys) (the secret and publishable keys).
- Pricing: [Stripe pricing](https://stripe.com/pricing) and, since Checkout charges tax, [Stripe Tax pricing](https://stripe.com/tax/pricing).
- Settings: `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` and `BILLING_PLAN_KEYS`, set together. `BILLING_TRIAL_PERIOD_DAYS` (default 14, `0` for none) sets the Trial.

### Support address and Operator details

- `SUPPORT_EMAIL` alone shows a support link and the address in the footer. Without it, both are hidden.
- `OPERATOR_NAME` and `OPERATOR_ADDRESS`, with `SUPPORT_EMAIL`, name the company that runs the Instance. They turn on the company footer, the Terms and Privacy Policy pages, the Terms notice at sign-in and, when the Instance sells Plans, accepting the Terms at checkout. `OPERATOR_VAT_ID`, `OPERATOR_REA`, `OPERATOR_SHARE_CAPITAL` and `OPERATOR_PEC` add company identifiers to the footer. Set them only together with [your own legal documents](#replace-the-legal-documents): the bundled ones are the Operator's, for pumpkit.io.
- Pricing: none.

```sh
curl -s http://localhost:8080/api/v1/instance | grep -o '"support_email":"[^"]*"'
```

**Check:** it prints `"support_email":"` and the address you set.

### PostHog

Product analytics behind the consent banner (ADR 0009), and optionally backend events and error tracking.

- Get a key: create a project at [PostHog](https://posthog.com) and copy its project API key.
- Pricing: [posthog.com/pricing](https://posthog.com/pricing).
- Settings: `POSTHOG_PROJECT_API_KEY` turns on browser analytics and the consent banner; `POSTHOG_ENABLED=true` adds backend events and error tracking. `POSTHOG_HOST` is the ingestion host (default `https://eu.i.posthog.com`; a US project uses `https://us.i.posthog.com`). `POSTHOG_RELAY=true` relays EU PostHog through `PUBLIC_URL/ph-relay`, past adblockers; then set `POSTHOG_HOST=PUBLIC_URL/ph-relay`.
- Without it: no analytics and no consent banner.

```sh
curl -s http://localhost:8080/api/v1/instance | grep -o '"analytics":{"key":"[^"]*"'
```

**Check:** it prints `"analytics":{"key":"` and your project key.

## Add or change a setting

To add a setting that `.env` does not hold yet, pass it to `scripts/setup.sh` as an environment variable, then restart the services that changed:

```sh
SUPPORT_EMAIL=help@example.org sh scripts/setup.sh </dev/null
docker compose up -d --wait
```

**Check:** `setup.sh` prints `Set: SUPPORT_EMAIL`, and `docker compose up` recreates the backend, the publisher and the web server and ends with every service `Healthy`.

`setup.sh` never overwrites a value already in `.env`: for a passed value it prints `Kept the value already in .env, ignoring the one passed:` and its name. To change one, edit its line in `.env`, then run `docker compose up -d --wait`. Keep `FERNET_ENCRYPTION_KEY` as it is: changing it makes stored X connections unreadable.

## Selling Plans

Turn this on only if you charge Users. You are then the seller: your own Terms, Privacy Policy and tax registration apply, not the Operator's.

1. **Create the Plans.** In Stripe, create a product with one recurring price per Plan, give each price a lookup key (for example `pro_monthly`), and set each price's tax behaviour to inclusive. Only the lookup keys in `BILLING_PLAN_KEYS` are on sale, in that order.
2. **Set up Stripe Tax.** Checkout charges tax and collects tax IDs, and Stripe refuses to open a Checkout until Stripe Tax is set up. Under Settings, then Tax, set the origin address and the default product category (for example "Software as a service (SaaS) - business use"), set "Include tax in prices" to Yes, and add a registration for each place you collect tax in. Without a registration, Checkout charges no tax. Pumpkit turns off Stripe's Managed Payments (Stripe as merchant of record, on by default for new accounts) for its Checkouts, so you stay the seller whatever that setting says.
3. **Add the webhook endpoint.** In Stripe's Developers section, add an endpoint at `PUBLIC_URL/api/v1/stripe/webhook` (for example `https://pumpkit.example.org/api/v1/stripe/webhook`) subscribed to `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted` and `checkout.session.completed`. Copy its signing secret.
4. **Write the settings.**

   ```sh
   STRIPE_SECRET_KEY='<sk_...>' STRIPE_PUBLISHABLE_KEY='<pk_...>' STRIPE_WEBHOOK_SECRET='<whsec_...>' \
     BILLING_PLAN_KEYS='["pro_monthly"]' sh scripts/setup.sh </dev/null
   docker compose up -d --wait
   curl -s http://localhost:8080/api/v1/instance | grep -o '"sells_plans":[a-z]*'
   ```

   **Check:** it prints `"sells_plans":true`, and `curl -s PUBLIC_URL/api/v1/billing/plans` lists each Plan with its price.
5. **Set the Operator details and replace the legal documents**, below, so Users accept your Terms at checkout.

Use Stripe's test mode keys first, buy a Plan with a [test card](https://docs.stripe.com/testing), and check that the Plan card in Settings shows the Subscription.

### Replace the legal documents

The Terms and Privacy Policy bundled with Pumpkit are the Operator's, for pumpkit.io, in English and Italian. They are part of the web image, so a Self-hoster who shows them builds the image from their own checkout:

1. Replace the four files in `frontend/src/features/legal/documents/` with your own, following [Changing the Terms or the Privacy Policy](development.md#changing-the-terms-or-the-privacy-policy) (it also covers the Terms version that checkout checks).
2. Set `OPERATOR_NAME`, `OPERATOR_ADDRESS` and `SUPPORT_EMAIL` with `setup.sh`.
3. Build and start from the checkout: `docker compose up -d --wait --build`. Upgrade the same way ([Upgrades](#upgrades), building from source).

```sh
curl -s http://localhost:8080/api/v1/instance | grep -o '"operator":{"name":"[^"]*"'
```

**Check:** it prints `"operator":{"name":"` and your company name, and `PUBLIC_URL/terms` shows your Terms.

## External Postgres

The stack bundles Postgres in the `db` service. To use a managed or existing Postgres instead, add these to `.env` (edit it, or pass them to `setup.sh` on a new `.env`), with your database's values:

```sh
COMPOSE_FILE=compose.yml:compose.external-db.yml
POSTGRES_HOST=db.example.org
POSTGRES_PORT=5432
POSTGRES_USER=pumpkit
POSTGRES_DB=pumpkit
POSTGRES_PASSWORD=<the database password>
POSTGRES_SSL=require
```

`COMPOSE_FILE` adds `compose.external-db.yml`, which leaves the `db` service out of every `docker compose` command. `POSTGRES_SSL=require` makes the backend and its migrations connect over SSL, which managed databases need; leave it out for a database without SSL. Instead of `COMPOSE_FILE`, you can pass `-f compose.yml -f compose.external-db.yml` to every command. The backend creates the tables on its first start.

```sh
docker compose up -d --wait
docker compose ps --services
curl -s http://localhost:8080/api/v1/health
```

**Check:** `ps --services` prints `backend`, `publisher` and `web` (no `db`), and the health check prints `{"status":"ok"}`.

## Backups and restore

These commands back up and restore the bundled Postgres. For an external one, use your provider's backups. Scheduling them (cron, a systemd timer) is up to you; keep copies off the server.

Back up, from the clone:

```sh
docker compose exec -T db pg_dump -U postgres -d postgres --format=custom > pumpkit-backup.dump
docker compose exec -T db pg_restore --list < pumpkit-backup.dump | grep -c 'TABLE DATA'
```

**Check:** the dump exits 0 and the second command prints the number of tables in the backup, such as `16`. If you set `POSTGRES_USER` or `POSTGRES_DB`, use those in place of `postgres`.

Also keep a copy of `.env`: without `FERNET_ENCRYPTION_KEY` a restored database cannot read its X connections.

Restore, which replaces the database's contents with the backup's:

```sh
docker compose stop backend publisher web
docker compose exec -T db pg_restore -U postgres -d postgres --clean --if-exists < pumpkit-backup.dump
docker compose up -d --wait
curl -s http://localhost:8080/api/v1/health
```

**Check:** `pg_restore` exits 0, `up` ends with every service `Healthy`, and the health check prints `{"status":"ok"}`. Users from the backup can sign in.

## Upgrades

Before 1.0, an upgrade may need manual steps. Each release lists them under **Upgrade notes** in [`CHANGELOG.md`](../CHANGELOG.md).

1. Read every CHANGELOG section between your version and the new one, and follow its **Upgrade notes**. Your version is `PUMPKIT_VERSION` in `.env`; releases are listed on [GitHub](https://github.com/pumpkit-io/pumpkit/releases).
2. [Back up](#backups-and-restore) the database.
3. Set `PUMPKIT_VERSION` in `.env` to the new version, without the `v` (for example `PUMPKIT_VERSION=0.2.0`).
4. Check out the new release, pull its images and restart:

   ```sh
   git fetch --tags
   git checkout v0.2.0
   docker compose pull
   docker compose up -d --wait
   ```

   Checking out the release keeps the compose files in step with the images. The backend applies new migrations when it starts.
5. Check the health and the running version:

   ```sh
   curl -s http://localhost:8080/api/v1/health
   docker compose images
   ```

   **Check:** `{"status":"ok"}`, and the `TAG` column shows the new version for `pumpkit-backend` and `pumpkit-web`.

### Building from source

`docker compose up -d --wait --build` builds both images from the checkout instead of pulling them, with the same compose file; the built images take the tag in `PUMPKIT_VERSION`. Use it to run your own changes, such as your own legal documents. To upgrade a source-built Instance, check out the new release (`git fetch --tags && git checkout v0.2.0`, merging your changes), set `PUMPKIT_VERSION`, and run `docker compose up -d --wait --build` instead of `docker compose pull`: a pull would replace your images with the release's.

## Search engines

An Instance is hidden from search engines by default: its pages carry `noindex,nofollow` and `robots.txt` disallows every path. Set `ALLOW_SEARCH_INDEXING=true` to allow indexing.

```sh
curl -s http://localhost:8080/robots.txt
```

**Check:** by default it prints `User-agent: *` and `Disallow: /`.

## Troubleshooting

Find the symptom, run the check it gives, and fix the cause.

**`setup.sh` prints `Missing required values:`.** It names each value it needs and the environment variable to set. Pass them and run it again; nothing was written.

**`docker compose up` fails with `port is already allocated` or `address already in use`.** Another program holds `HTTP_PORT` (default 8080) or `HTTPS_PORT` (default 443). On a laptop, set both to free ports in `.env`, such as `HTTP_PORT=8081`, `HTTPS_PORT=8444` and `PUBLIC_URL=http://localhost:8081`. On a server, stop whatever else serves ports 80 and 443 (`sudo ss -ltnp | grep -E ':(80|443) '` names it).

**`docker compose` prints `denied` for a `ghcr.io/pumpkit-io` image.** No published release has the version in `PUMPKIT_VERSION`. `docker compose up` then builds the images from the checkout instead (the output goes on with `Building`), which works but takes several minutes; `docker compose pull` fails. Check the version against [the releases](https://github.com/pumpkit-io/pumpkit/releases).

**`docker compose up --wait` fails because `backend` is unhealthy.** Read why:

```sh
docker compose logs backend | grep -o 'Value error, [^[]*' | tail -1
```

A line such as `Value error, SMTP is partly configured; missing: EMAIL_FROM` names the provider settings to complete or remove. If it prints nothing, read the end of the log with `docker compose logs --tail 50 backend`. A database connection error there means the `POSTGRES_*` settings are wrong; with an external database, also check `POSTGRES_SSL`.

**The health check prints `{"status":"unavailable"}`.** The backend cannot reach Postgres. `docker compose ps db` shows whether the bundled database is healthy; for an external one, check the host, port, password and `POSTGRES_SSL`.

**`curl` to `PUBLIC_URL` on a server fails or the browser reports a certificate error.** Caddy could not get a certificate. Check that DNS points at the server (`dig +short` in [step 1](#1-check-the-prerequisites)), that ports 80 and 443 are open, and that `.env` has `HTTP_PORT=80`. `docker compose logs web | grep -i obtain` shows Caddy's attempts. After a fix, `docker compose restart web`.

**No Magic link arrives.** Without SMTP, it is in the log (`docker compose logs backend | grep "Magic link for"`). With SMTP, look for a send error in `docker compose logs --tail 50 backend`, check your provider's sending logs, and check that `EMAIL_FROM` is on a verified domain. A Magic link expires after 15 minutes and works once.

A `TimeoutError` in that log means the server can't reach the SMTP port. Some cloud providers, DigitalOcean among them, block 25, 465 and 587 going out. Check from the server, with your `SMTP_HOST` and port:

```sh
timeout 6 bash -c 'echo > /dev/tcp/smtp.resend.com/587' && echo open || echo blocked
```

If it prints `blocked`, set `SMTP_PORT` to another port your provider listens on (Resend also takes `starttls` on 2587 and `tls` on 2465), then run `docker compose up -d --wait backend`.

**The sign-in page has no Google button.** The Google group is unset. See [Google sign-in](#google-sign-in).

**Google sign-in fails with `redirect_uri_mismatch`.** The OAuth client's redirect URI must be exactly `PUBLIC_URL/api/v1/oauth/google/callback`.

**Adding an Inspiration author shows "X can't be read right now. Please try again later."** twitterapi.io refused the request. `docker compose logs backend | grep "twitterapi.io returned" | tail -1` prints the status: `twitterapi.io returned HTTP 401` means `TWITTERAPI_IO_API_KEY` is wrong; for another status, check your account and credit on the twitterapi.io dashboard.

**Writing a Post fails.** The LLM key is wrong or has no credit, or `LLM_BASE_URL` and the three models don't match. `docker compose logs --tail 50 backend` shows the endpoint's error.

**Connecting X fails.** The X group is unset, or the X app's callback URL is not exactly `PUBLIC_URL/oauth/x/callback`, or the app is not an OAuth 2.0 confidential client with read and write permissions.

**A Scheduled post does not go out.** `docker compose ps publisher` should show `(healthy)`; `docker compose logs --tail 50 publisher` shows its passes and any error from X. A Failed Scheduled post shows its reason on the Posts page.

**Stripe Checkout fails, or a paid Subscription does not show.** Check Stripe Tax ([Selling Plans](#selling-plans), step 2) and the backend log, which has Stripe's reason. On Stripe's webhook endpoint page, check that deliveries to `PUBLIC_URL/api/v1/stripe/webhook` succeed.
