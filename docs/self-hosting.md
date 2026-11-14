# Self-hosting Pumpkit

For an explicitly authorized prelaunch test-account reset, use the [X-only cutover procedure](x-only-cutover.md). Its privileged preview/execute mode is separate from ordinary deletion and never runs automatically.

This guide runs your own Instance of Pumpkit with Docker Compose, on your computer or on a server. It is the source of truth for the prompt in the README: an agent following that prompt follows this guide.

Every step is a command, then a **Check** with its expected output. Run the check before moving on. When a check fails, stop and look the symptom up in [Troubleshooting](#troubleshooting).

## For agents

Run the [install](#install) steps in order, with these rules:

1. Before changing anything, ask whether to run Pumpkit on this computer (the laptop path) or on a server reachable over SSH (the server path). For a server, also ask for the SSH host and the domain name. On the server path, run every command on the server, in the clone, with `ssh <host> '<command>'`, except where a step says to run it on this computer.
2. Ask for provider keys one provider at a time, in the order of [Providers](#providers). For each, tell the self-hoster where to get the key, link its pricing page (the guide gives no prices, because they change), and say what stops working without it. The three required providers come first; for each optional one, ask whether they want it and skip it when they don't.
3. Pass keys to `scripts/setup.sh` as environment variables, never as flags, and never print `.env` or a key. `.env` is git-ignored; leave it uncommitted.
4. When you finish, run the [health check](#5-check-the-health-endpoint), then tell the self-hoster the URL to open and how to sign in ([step 6](#6-sign-in)). Explain that X alone signs users in and the X app must supply confirmed email and publishing permissions.

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

`scripts/setup.sh` writes `.env` from `.env.example`, generates the database password, signing/encryption secrets and trial identity key ring, and sets the file's mode to 600. It never prints a secret, and on a second run it keeps every value already in `.env`. Get the required [X app credentials](#x-app-required), [LLM key](#llm-endpoint-required) and [twitterapi.io key](#twitterapiio-required) first. Every instance requires X, even one selling no plans.

Choose `PUBLIC_URL`, the address Users open:

| Path   | `PUBLIC_URL`                               | Also pass                                                                                      |
| ------ | ------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| Laptop | `http://localhost:8080`                    | nothing; with port 8080 taken, `--http-port 8081` and `--public-url http://localhost:8081`     |
| Server | `https://pumpkit.example.org`, your domain | `--http-port 80`, and optionally `--acme-email you@example.org` for certificate expiry notices |

`PUBLIC_URL` must be an address the clients can reach, not only the browser: AI apps connect to `PUBLIC_URL/api/v1/mcp` (see [docs/mcp.md](mcp.md)). claude.ai and ChatGPT connect from their own servers, so they need a `PUBLIC_URL` reachable from the internet over HTTPS. A laptop's `http://localhost:8080` works only for apps running on that laptop, such as Claude Code. Connecting apps needs no setting of its own.

An `https://` `PUBLIC_URL` gets a certificate automatically; an `http://` one is served as plain HTTP on any host. The web container listens on `HTTP_PORT` (default 8080, for laptops) and `HTTPS_PORT` (default 443). A server needs `HTTP_PORT=80`: port 80 serves the redirect from HTTP to HTTPS and answers the certificate authority's HTTP-01 challenge.

Laptop:

```sh
X_CLIENT_ID='<your X client ID>' X_CLIENT_SECRET='<your X client secret>' \
LLM_API_KEY='<your LLM key>' TWITTERAPI_IO_API_KEY='<your twitterapi.io key>' \
  sh scripts/setup.sh --public-url http://localhost:8080 </dev/null
```

Server:

```sh
X_CLIENT_ID='<your X client ID>' X_CLIENT_SECRET='<your X client secret>' \
LLM_API_KEY='<your LLM key>' TWITTERAPI_IO_API_KEY='<your twitterapi.io key>' \
  sh scripts/setup.sh --public-url https://pumpkit.example.org --http-port 80 </dev/null
```

To add optional providers now, put their settings in the same command as environment variables (each provider below names them); you can also add them later with [Add or change a setting](#add-or-change-a-setting). In a terminal, `sh scripts/setup.sh` with no arguments asks for each missing required value instead.

**Check:** the output is:

```
Wrote /path/to/pumpkit/.env (mode 600).
Generated: POSTGRES_PASSWORD JWT_SECRET_KEY FERNET_ENCRYPTION_KEY TRIAL_IDENTITY_KEYS
Set: PUBLIC_URL LLM_API_KEY TWITTERAPI_IO_API_KEY X_CLIENT_ID X_CLIENT_SECRET
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

Open `PUBLIC_URL`, choose **Get started**, then **Continue with X**. X must return a confirmed email and all requested sign-in and publishing permissions. With plans configured, the paywall comes first; otherwise you go directly to **Persona**. Choose your inspiration authors and Continue to finish onboarding, then write a brief on **New post**.

**Check:** metadata at `PUBLIC_URL/api/v1/instance` lists only `"sign_in_methods":["x"]`; returning with the same X account opens the same Pumpkit account. Changing its email or handle does not create another account. Confirm an email on X and retry if the sign-in page says one is missing.

Profile shows the X handle, confirmed email and X photo (initials when unavailable). You may edit your Pumpkit name; later sign-ins preserve that edit. X identity and photo cannot be replaced or disconnected in Settings. If publishing access is lost, **Reconnect X** accepts only that same X account; writing, billing and deletion keep their usual access rules. Sign out and sign in with a different X account to use its separate Pumpkit account.

### 7. Restrict sign-ups if needed

Set a [Sign-up allowlist](#sign-up-allowlist) before sharing the address if only some people may sign in. It checks X's confirmed email on each sign-in. SMTP is not needed for authentication, and Google, magic link and mail settings never enable another sign-in method.

## Providers

Pumpkit needs X, an LLM endpoint and twitterapi.io. Every other one is optional: with none of its settings, it is off and the rest of Pumpkit works without it. With only some of a provider's settings, the backend refuses to start and names the missing ones. [`docs/configuration.md`](configuration.md) describes every setting.

### LLM endpoint (required)

Writes every Post and drafts each Positioning. Pumpkit calls any OpenAI-compatible endpoint, [OpenRouter](https://openrouter.ai) by default.

- Get a key: [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys).
- Pricing: [OpenRouter pricing](https://openrouter.ai/pricing); Pumpkit's default model is [`openai/gpt-5.6-luna`](https://openrouter.ai/openai/gpt-5.6-luna), whose page lists its price per token. Each Version makes two model calls. Starting a Post first makes one more to plan it, and a Positioning draft makes one, both on [`openai/gpt-6-luna`](https://openrouter.ai/openai/gpt-6-luna) by default.
- Settings: `LLM_API_KEY`. For another endpoint, also set `LLM_BASE_URL` and the five models it serves: `LLM_SKETCHING_MODEL`, `LLM_HUMANIZING_MODEL`, `LLM_REVISING_MODEL`, `LLM_PLANNING_MODEL` and `LLM_POSITIONING_MODEL`.
- Without it: `scripts/setup.sh` refuses to write `.env`. With a wrong key, writing a Post fails.
- **Check:** a Post you write gets a Version ([step 6](#6-sign-in)).

### twitterapi.io (required)

Reads the recent posts of each Inspiration author, which set the style Pumpkit writes in (ADR 0005), and the name of each Community a User pastes to post into.

- Get a key: sign up at [twitterapi.io](https://twitterapi.io/dashboard); the key is on the dashboard.
- Pricing: [twitterapi.io pricing](https://twitterapi.io/pricing).
- Settings: `TWITTERAPI_IO_API_KEY`.
- Without it: `scripts/setup.sh` refuses to write `.env`. With a wrong key, adding an Inspiration author fails, and a User with no Inspiration author cannot write a Post. A pasted Community shows its ID instead of its name, and posting into it still works.
- **Check:** adding an X handle on the **Persona** page lists it.

### Inactive legacy sign-in implementations

Google and magic link implementations, their mail delivery and Gravatar adapters remain in the source for deliberate adaptations. They are not mounted in the stock app. Configuring Google credentials or SMTP does not offer another button, send sign-in mail or enable old callback URLs. There is no supported method-selection setting. See [the inactive settings](configuration.md#retained-inactive-sign-in-settings).

### Sign-up allowlist

Not a provider, but set it before you share the address if only some people may sign in.

- Settings: `SIGN_UP_ALLOWLIST`, comma-separated addresses and `@domain` entries, such as `me@example.org,@team.example.org`.
- Without it: anyone who can reach the Instance can sign in.
- **Check:** signing in with an X account whose confirmed email is outside the list shows "This site doesn't accept sign-ins from that email address." on the sign-in page.

### X app (required)

X alone signs users in and authorizes publishing for the same stable X account (ADR 0023). Your X app pays for every publish. Verify access to `tweet.read tweet.write users.read offline.access media.write users.email` and confirmed email, name and photo fields with the configured real app before rollout. A local stand-in does not prove X entitlement.

- Get credentials: in the [X developer portal](https://developer.x.com/en/portal/dashboard), create an app and set up its user authentication: OAuth 2.0, app type **Web App, Automated App or Bot** (a confidential client), permissions **Read and write**. Register this callback URL: `PUBLIC_URL/oauth/x/callback` (for example `https://pumpkit.example.org/oauth/x/callback`), and use `PUBLIC_URL` as the website URL. Copy the OAuth 2.0 client ID and client secret.
- Pricing: [X API pricing](https://docs.x.com/x-api/getting-started/pricing). `X_POSTS_MONTHLY_CAP` (default 100 X posts per User per month, each Part of a Thread counting as one) and `X_LINK_POSTS_MONTHLY_CAP` (default 10 of them with a link, which X charges far more for) bound what each User can cost you; set either empty for no cap. With Plans they count per Allowance period, a quarter for the Trial; without, per UTC calendar month.
- Settings: `X_CLIENT_ID` and `X_CLIENT_SECRET`.
- Without it: startup refuses to run. There is no alternate sign-in during an X outage. Existing valid sessions continue under their usual rules.
- **Check:** `curl -s PUBLIC_URL/api/v1/instance` shows `"sign_in_methods":["x"]`. Complete first and returning sign-in, then same-account reconnect, with the exact registered `PUBLIC_URL/oauth/x/callback`. Missing confirmed-email support blocks rollout rather than enabling a fallback.

### Stripe billing

Sells Plans. Without it the Instance sells no Plans and every signed-in User may use all of Pumpkit. See [Selling Plans](#selling-plans) for the whole setup.

- Get keys: [dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys) (the secret and publishable keys).
- Pricing: [Stripe pricing](https://stripe.com/pricing) and, since Checkout charges tax, [Stripe Tax pricing](https://stripe.com/tax/pricing).
- Settings: `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` and `BILLING_PLAN_KEYS`, set together. `BILLING_TRIAL_PERIOD_DAYS` (default 7, `0` for none) sets the Trial. `GENERATIONS_MONTHLY_CAP` (default 500 per month, a quarter for the Trial, empty for no cap) sets how many Versions each Subscribed User may have written. `BILLING_TOP_UP_KEY` (optional) sells Top-ups.

### Support address and Operator details

- `SUPPORT_EMAIL` alone shows a support link and the address in the footer. Without it, both are hidden.
- `OPERATOR_NAME`, with `SUPPORT_EMAIL`, names the company that runs the Instance. It turns on the company line in the footer, the Terms and Privacy Policy pages, the Terms notice at sign-in and, when the Instance sells Plans, accepting the Terms at checkout. `OPERATOR_VAT_ID` adds the VAT ID to the company line. The rest of the company details belong in your Terms, which the footer's Company details link opens at the section with the `operator` anchor. Set `OPERATOR_NAME` only together with [your own legal documents](#replace-the-legal-documents): the bundled ones are the Operator's, for pumpkit.io.
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
3. **Add the webhook endpoint.** In Stripe's Developers section, add an endpoint at `PUBLIC_URL/api/v1/stripe/webhook` (for example `https://pumpkit.example.org/api/v1/stripe/webhook`) subscribed to `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `charge.refunded` and `charge.dispute.created`. Copy its signing secret.
4. **Write the settings.**

   ```sh
   STRIPE_SECRET_KEY='<sk_...>' STRIPE_PUBLISHABLE_KEY='<pk_...>' STRIPE_WEBHOOK_SECRET='<whsec_...>' \
     BILLING_PLAN_KEYS='["pro_monthly"]' sh scripts/setup.sh </dev/null
   docker compose up -d --wait
   curl -s http://localhost:8080/api/v1/instance | grep -o '"sells_plans":[a-z]*'
   ```

   **Check:** it prints `"sells_plans":true`, and `curl -s PUBLIC_URL/api/v1/billing/plans` lists each Plan with its price.

5. **Sell Top-ups, if you want to.** A Top-up is a one-off pack, half of each monthly cap (250 generations and 50 X posts, up to 5 with a link, at the defaults), that a paid-up User buys once they run low; it lasts 12 months and is spent only after the Allowance. In Stripe, add a one-off price (not recurring) to a product, give it a lookup key such as `top_up`, set its tax behaviour to inclusive, and set `BILLING_TOP_UP_KEY=top_up` in `.env`. Leave the setting out and no Top-ups are sold. A refund or a dispute of a Top-up's payment in Stripe removes whatever is left of it; what it already paid for, waiting Scheduled posts included, stays paid for and doesn't move onto the Allowance. Your Terms should say that a Top-up is not refunded once any of it is spent.

   **Check:** `curl -s PUBLIC_URL/api/v1/billing/plans` shows `top_up` with its price.

6. **Set the Operator details and replace the legal documents**, below, so Users accept your Terms at checkout.

Use Stripe's test mode keys first, buy a Plan with a [test card](https://docs.stripe.com/testing), and check that the Plan card in Settings shows the Subscription.

### Replace the legal documents

The Terms and Privacy Policy bundled with Pumpkit are the Operator's, for pumpkit.io, in English and Italian. They are part of the web image, so a Self-hoster who shows them builds the image from their own checkout:

1. Replace the four files in `frontend/src/features/legal/documents/` with your own, following [Changing the Terms or the Privacy Policy](development.md#changing-the-terms-or-the-privacy-policy) (it also covers the Terms version that checkout checks).
   Keep a section headed with `{#operator}` in your Terms for your company details: the footer's Company details link opens it.
2. Set `OPERATOR_NAME` and `SUPPORT_EMAIL` with `setup.sh`.
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

## A proxy in front of the web server

Pumpkit's per-IP rate limits (X sign-in and connected AI app authorization) need each caller's real address. With the bundled stack that works with no setting: the web server passes the caller's address to the backend in `X-Forwarded-For`, and the backend trusts it from the private ranges Docker allocates from (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`). `compose.external-db.yml` only swaps the database, so it is unaffected.

If your own proxy, load balancer or CDN sits in front of the web server, it must send `X-Forwarded-For` with the caller's address, and two settings tell each hop to believe it:

- `TRUSTED_PROXIES` for the web server (Caddy): your proxy's address or range as the web server sees it, separated by spaces (`203.0.113.10 10.1.0.0/16`). Without it Caddy replaces the header with your proxy's address, so every caller looks like your proxy. Caddy needs this because it discards a forwarded address from any peer it was not told to trust.
- `FORWARDED_ALLOW_IPS` for the backend (uvicorn): comma-separated addresses or ranges. The header then reaches the backend as `caller, your-proxy`, and the backend takes the first address it does not trust, so set it when your proxy has a public address: list your proxy's address next to the private ranges, which this setting replaces (`127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,203.0.113.10`). A proxy on a private address needs no change. Never set it to `*` while the backend's port is reachable from outside the compose network.

Your proxy must also forward `/.well-known/oauth-*` and `/.well-known/openid-configuration` to the web server, as well as `/api/*`. AI apps find how to sign in there, and `sh scripts/check-stack.sh PUBLIC_URL` fails when those paths do not reach the backend.

Your proxy must also let Media uploads through: a video can be up to 512 MB, sent in one request that can take many minutes on a slow connection. Allow request bodies of at least 520 MiB (nginx's `client_max_body_size 520m`, which defaults to 1 MB), and no time limit, or a long one, on reading a request's body. The bundled web server allows that much only on the upload paths, and 10 MiB elsewhere.

Set them in `.env`, then run `docker compose up -d --wait`. Check X sign-in initiation from different addresses: one address reaching its limit must not rate-limit the others.

## Backups and restore

These commands back up and restore the bundled Postgres and the `media_data` volume. For an external Postgres, use your provider's backups for the database. Scheduling them (cron, a systemd timer) is up to you; keep copies off the server.

The `media_data` volume holds Media: the images, GIFs and videos Users attach to their posts, kept until each goes out on X. The publisher deletes the files of Media no post uses any more, such as an image a User removed. Back it up together with the database, which records which files belong to which post; a database restored without its Media leaves those posts unable to publish their Media.

Back up, from the clone:

```sh
docker compose exec -T db pg_dump -U postgres -d postgres --format=custom > pumpkit-backup.dump
docker compose exec -T db pg_restore --list < pumpkit-backup.dump | grep -c 'TABLE DATA'
```

**Check:** the dump exits 0 and the second command prints the number of tables in the backup, such as `16`. If you set `POSTGRES_USER` or `POSTGRES_DB`, use those in place of `postgres`.

Then the Media:

```sh
docker compose exec -T backend tar czf - -C /var/lib/pumpkit/media . > pumpkit-media.tar.gz
tar tzf pumpkit-media.tar.gz | wc -l
```

**Check:** `tar` exits 0 and the second command prints a count of at least `1`, the archive's top directory.

Also keep a protected copy of `.env`: without `FERNET_ENCRYPTION_KEY` a restored database cannot read its X connections. Keep the complete `TRIAL_IDENTITY_KEYS` and, when configured, `COUPON_IDENTITY_KEYS` rings encrypted separately and restore the matching historical keys with the database. A missing referenced key makes unproven eligibility decisions fail closed. Never replace bytes under an existing key ID: that breaks matching and cannot be treated as a safe rotation. The minimal eligibility fingerprints survive account deletion for the instance's lifetime. See [X account trial eligibility](configuration.md#x-account-trial-eligibility) for rotation and retention.

Restore, which replaces the database's contents with the backup's:

```sh
docker compose stop backend publisher web
docker compose exec -T db pg_restore -U postgres -d postgres --clean --if-exists < pumpkit-backup.dump
docker compose run --rm --no-deps -T backend sh -c 'find /var/lib/pumpkit/media -mindepth 1 -delete && tar xzf - -C /var/lib/pumpkit/media' < pumpkit-media.tar.gz
docker compose up -d --wait
curl -s http://localhost:8080/api/v1/health
```

**Check:** `pg_restore` and `tar` exit 0, `up` ends with every service `Healthy`, and the health check prints `{"status":"ok"}`. Users from the backup can sign in.

## Upgrades

Before 1.0, an upgrade may need manual steps. Each release lists them under **Upgrade notes** in [`CHANGELOG.md`](../CHANGELOG.md).

1. Read every CHANGELOG section between your version and the new one, and follow its **Upgrade notes**. Your version is `PUMPKIT_VERSION` in `.env`; releases are listed on [GitHub](https://github.com/pumpkit-io/pumpkit/releases).
2. [Back up](#backups-and-restore) the database and the Media.
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

6. Run any one-off command the **Upgrade notes** ask for, once, inside the running backend. For example, the author photo backfill:

   ```sh
   docker compose exec backend python -m pumpkit.authors.photo_backfill
   ```

   **Check:** its last line reports how many it filled and how many it skipped. Running it again only retries the skipped ones.

### X-only account cutover

Before starting this release, configure the required X credentials and exact callback, verify confirmed-email and publishing permissions, and preserve `FERNET_ENCRYPTION_KEY` plus the complete trial and coupon identity key rings with a matching database backup. Apply migrations through `0057`. Setup generates an initial trial ring only when absent; never generate a replacement for an existing database's ring. Retained eligibility and X claim records guard their own downgrades, so rollback may require a compatible backup.

Legacy accounts are not automatically migrated, linked by email or deleted. Plan any deliberate clean reset through supported account-deletion and billing-settlement procedures before cutover; the operator's authorization for their test data does not authorize deletion on a self-hoster's instance. Never delete database rows to bypass pending billing or publishing guards. Ordinary account deletion preserves lifetime trial eligibility and the separate coupon claim retention. In-flight old X authorizations may need to be restarted after upgrading.

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

**X sign-in is refused or loops.** Check the exact registered `PUBLIC_URL/oauth/x/callback`, confidential-client credentials and all required scopes, including `users.email`. A user without confirmed email must confirm it on X and retry. A cancelled, expired or pre-upgrade authorization needs a fresh **Continue with X**. Google and magic link routes are inactive regardless of credentials or SMTP.

**Adding an Inspiration author shows "X can't be read right now. Please try again later."** twitterapi.io refused the request. `docker compose logs backend | grep "twitterapi.io returned" | tail -1` prints the status: `twitterapi.io returned HTTP 401` means `TWITTERAPI_IO_API_KEY` is wrong; for another status, check your account and credit on the twitterapi.io dashboard.

**Writing a Post fails.** The LLM key is wrong or has no credit, or `LLM_BASE_URL` and the three models don't match. `docker compose logs --tail 50 backend` shows the endpoint's error.

**Reconnecting X fails.** Use the same X account you signed in with. Check whether the X app's callback URL is not exactly `PUBLIC_URL/oauth/x/callback`, or the app is not an OAuth 2.0 confidential client with read and write permissions.

**A Scheduled post does not go out.** `docker compose ps publisher` should show `(healthy)`; `docker compose logs --tail 50 publisher` shows its passes and any error from X. A Failed Scheduled post shows its reason on the Posts page.

**Stripe Checkout fails, or a paid Subscription does not show.** Check Stripe Tax ([Selling Plans](#selling-plans), step 2) and the backend log, which has Stripe's reason. On Stripe's webhook endpoint page, check that deliveries to `PUBLIC_URL/api/v1/stripe/webhook` succeed.

## Coupon readiness

Coupons are being implemented under spec #392 and remain disabled by default until final Stripe validation #394. [The coupon contract](coupons.md) sets the cardless acceptance, retention/purge and key backup/rotation rules that the runtime slices must implement. Replace the bundled bilingual legal documents for your instance and apply your own material-change notice process. Apply the runtime release’s migrations and Upgrade notes; do not activate from historical provider evidence alone.

### Coupon tooling

Billing-enabled instances can issue, inspect and permanently disable coupons with the [privileged commands](coupons.md#privileged-coupon-commands). This adds no public issuance endpoint. `COUPONS_ENABLED` stays off by default until the complete feature passes final Stripe validation. An instance selling no plans needs no coupon setting, key or purge job.

Before isolated testing, apply migrations, configure `COUPON_IDENTITY_KEYS`, back up its complete key ring securely and separately from the database, and schedule daily purge with the same protected configuration. Restore matching keys and database together. Keep old keys during rotation; otherwise existing assignments and claims fail closed. [The contract](coupons.md#identity-and-key-custody) explains retention and rotation. Existing billing needs no manual change while coupons remain off.

Before eventual activation, configure `STRIPE_COUPON_PORTAL_CONFIGURATION_ID` with subscription updates/cancellation and portal login disabled. Settings supplies cancellation and deferred frequency changes while the portal manages payment methods/invoices. Inventory older portal configurations, login links and outstanding sessions and establish their safe handling in final #394; a new configuration ID does not revoke them. Add `python -m pumpkit.billing.plan_change_recovery recover` to existing daily recovery checks, keep migrations through `0053` installed and audit pre-0053 deferrals as [the recovery contract](coupons.md#deferral-dispatch-recovery-and-upgrade-audit) describes, and investigate every unresolved operation. The [complete supported flow](coupons.md#deferred-billing-frequency-changes) preserves paid/free dates and monthly allowance across annual/monthly changes.
