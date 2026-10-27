# Changelog

Every release of Pumpkit gets a section here, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

Before 1.0, upgrades may need manual steps. Read the section for every version between yours and the one you are upgrading to, and follow any steps listed under **Upgrade notes**.

## [Unreleased]

### Changed

- Install and upgrade from the latest release tag instead of `main`, so the compose file, `setup.sh` and the docs match the release images. **Upgrade notes:** upgrade with `git fetch --tags && git checkout vX.Y.Z` instead of `git pull` (see Upgrades in `docs/self-hosting.md`).

## [0.1.0] - 2026-10-12

The first release that a Self-hoster can install.

### Added

- Prebuilt images for every release, for amd64 and arm64: `ghcr.io/pumpkit-io/pumpkit-backend` (backend and publisher) and `ghcr.io/pumpkit-io/pumpkit-web` (the built frontend served by Caddy, with automatic HTTPS). Pin a release with `PUMPKIT_VERSION` in `.env`.
- A production Docker Compose file at the repo root that runs a whole Instance: Postgres, backend, publisher and web. The backend applies database migrations when it starts, and the publisher starts once the backend is healthy. `compose.external-db.yml` swaps the bundled Postgres for an external one.
- `scripts/setup.sh`, which writes `.env` with every secret generated, keeps values already there, never prints a secret, and names each missing required value when run without a terminal.
- `GET /api/v1/health`, which answers 200 when the backend can reach the database and 503 when it cannot.
- `GET /api/v1/instance`, which tells the frontend the app name, sign-in methods, whether the Instance sells Plans, the Operator details and the analytics settings.
- Optional providers. Stripe billing, SMTP email, Google sign-in, Operator details and PostHog analytics each turn on when their settings are set and off when none are; a partly configured provider stops the backend at startup and names the missing settings. Without Stripe, every signed-in User has full access; without SMTP, Magic links go to the backend log; without Google, sign-in offers only Magic links; without Operator details, the legal pages and company footer are hidden.
- A Sign-up allowlist (`SIGN_UP_ALLOWLIST`) of addresses and `@domain` entries that may sign in.
- Any OpenAI-compatible LLM endpoint (`LLM_BASE_URL`, `LLM_API_KEY`), with the drafting, humanizing and revising models as settings.
- `POSTGRES_SSL` to require SSL on the database connection, independent of `ENV`.
- `ALLOW_SEARCH_INDEXING`, off by default, so an Instance is hidden from search engines unless it opts in.
- `docs/self-hosting.md`, the guide to running an Instance on a laptop or a server, which the README's prompt asks an AI agent to follow.
- A root `Makefile` with `dev`, `check`, `test`, `fmt`, `e2e` and `smoke`, which CI also runs.

### Changed

- One root `.env` holds every setting; `PUBLIC_URL` derives the frontend and API URLs, CORS origins, Magic link base, OAuth redirect URIs and Stripe return URLs.
- The frontend calls the API on its own origin, so `VITE_API_URL` and the other build-time `VITE_*` settings are gone.
- Email is sent over SMTP (`SMTP_*`, `EMAIL_FROM`) instead of Resend; the support address is `SUPPORT_EMAIL`.
- `OPENROUTER_API_KEY` is now `LLM_API_KEY`.
- The development stack moved to `compose.dev.yml` (`make dev`) and runs the frontend on Node 22, as CI does.
- An empty Scheduled posts cap means no cap; 0 still turns scheduling off.

### Removed

- `backend/.env.example` and `frontend/.env.example`.
- The systemd deploy: the publisher's systemd unit, `infra/Caddyfile`, `scripts/deploy.sh` with its `deploy.env.example` and PostHog deploy annotations, and `docs/deployment.md`. Deploy with the production compose file instead, following `docs/self-hosting.md`.
