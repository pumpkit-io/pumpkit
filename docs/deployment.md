# Deployment

The template ships a single-server deployment: Caddy terminates TLS, serves the
built frontend and proxies `/api/*` to the FastAPI backend, which runs as a
systemd service. `scripts/deploy.sh` performs every deploy after the one-time
setup below. Docker Compose is for local development only.

## 1. Provision the server (once)

Any Ubuntu 22.04+/Debian 12 VM works (e.g. a DigitalOcean droplet).

```bash
# As root
apt-get update && apt-get install -y git curl build-essential debian-keyring debian-archive-keyring apt-transport-https
# Node 20
curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y nodejs
# Caddy
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
apt-get update && apt-get install -y caddy
# App user + uv
adduser --disabled-password --gecos "" pumpkit
sudo -u pumpkit bash -lc 'curl -LsSf https://astral.sh/uv/install.sh | sh'
```

## 2. Database

Use a managed Postgres (recommended) or install one locally. With `ENV=prod`
the backend and Alembic connect with SSL (`sslmode=require` / `ssl=require`),
which managed providers require. A local Postgres must then have SSL enabled.

## 3. Code and environment files

```bash
sudo -u pumpkit git clone git@github.com:<you>/<repo>.git /home/pumpkit/app
```

Give the server read access to the repo with a deploy key (`ssh-keygen` as
`pumpkit`, add the public key to the repository's deploy keys).

Create, as `pumpkit`:
- `/home/pumpkit/app/.env`: from `.env.example`, with `ENV=prod`, real `POSTGRES_*`, `BACKEND_URL`/`FRONTEND_URL` = `https://<domain>`, `CORS_ORIGINS='["https://<domain>"]'`.
- `/home/pumpkit/app/backend/.env`: from `backend/.env.example`, with production secrets and `https://<domain>/billing/...` Stripe URLs.
- `/home/pumpkit/app/frontend/.env`: `VITE_API_URL=https://<domain>/api/v1`, `VITE_APP_NAME`, optional PostHog (`VITE_POSTHOG_HOST=https://<domain>/ph-relay`).

## 4. Backend service

`/etc/systemd/system/pumpkit-backend.service`:

```ini
[Unit]
Description=Pumpkit backend
After=network-online.target

[Service]
User=pumpkit
WorkingDirectory=/home/pumpkit/app/backend
EnvironmentFile=/home/pumpkit/app/.env
EnvironmentFile=/home/pumpkit/app/backend/.env
ExecStartPre=/home/pumpkit/.local/bin/uv run alembic upgrade head
ExecStart=/home/pumpkit/.local/bin/uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable pumpkit-backend
```

### Publisher

The publisher publishes due Scheduled posts on X. It runs as its own unit, so API
deploys and restarts don't interrupt it (ADR 0007). Its unit is
`infra/pumpkit-publisher.service`: same user, directory and environment files as the
backend, no migrations, `uv run python -m app.publishing`. `scripts/deploy.sh` copies
it to `/etc/systemd/system/`, enables it and restarts it after the backend, so there's
nothing to install by hand. To start it before the first deploy:

```bash
cp /home/pumpkit/app/infra/pumpkit-publisher.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now pumpkit-publisher
```

It looks for due Scheduled posts every `PUBLISHER_POLL_INTERVAL_SECONDS` (30 by
default). Check it with `journalctl -u pumpkit-publisher`. One publisher is enough;
a second one wouldn't publish anything twice, but it wouldn't speed anything up.

## 5. Caddy

Give Caddy the values `infra/Caddyfile` reads:

```bash
systemctl edit caddy
# add:
# [Service]
# Environment=DOMAIN=example.com ACME_EMAIL=ops@example.com APP_DIR=/home/pumpkit/app
```

Point the domain's A/AAAA records (and `www`) at the server. The first deploy
copies `infra/Caddyfile` to `/etc/caddy/Caddyfile` and reloads Caddy, which
then obtains certificates automatically.

Writing a Version answers only after two model calls, which can take a couple of
minutes, so the Caddyfile lets the backend take up to 5 minutes to respond. Uvicorn
and the frontend's API client set no request timeout of their own.

## 6. Stripe webhook

In the Stripe dashboard add an endpoint `https://<domain>/api/v1/stripe/webhook`
subscribed to: `customer.subscription.created`, `customer.subscription.updated`,
`customer.subscription.deleted` and `checkout.session.completed`. Put its signing
secret in `STRIPE_WEBHOOK_SECRET`.

## 7. X app

Scheduled posts publish through the X app whose `X_CLIENT_ID` and `X_CLIENT_SECRET`
are in `backend/.env`. In the X developer portal, add
`https://<domain>/oauth/x/callback` to the app's callback URLs and set the same value
as `X_REDIRECT_URI`.

## 8. Deploy

On your machine: `cp deploy.env.example deploy.env`, fill it in (the SSH host
alias must log in as root or a sudoer), then:

```bash
bash scripts/deploy.sh
```
