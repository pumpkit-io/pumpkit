# Pumpkit

Open-source AI writing tool for X: turns a brief into a post written in the style of X authors you choose, then revises it with your feedback.

## Stack and commands

- Backend: Python 3.13, FastAPI, SQLAlchemy, Alembic, managed with **uv** (`backend/`). Frontend: React, Vite, TypeScript, Tailwind, managed with **npm** (`frontend/`). E2E: Playwright, npm (`e2e/`).
- Dev: `docker compose up --build` (Postgres, backend on :8000, frontend on :5173)
- Lint: `cd backend && uv run ruff check .` · `cd frontend && npm run lint`
- Format: `cd backend && uv run ruff format .` · `cd frontend && npm run format` (same in `e2e/`)
- Typecheck: `cd backend && uv run --extra dev pyright` · `cd frontend && npm run typecheck` (same in `e2e/`)
- Test: `cd backend && uv run --extra dev pytest` (SQLite, no services needed) · `cd frontend && npm test` · `cd e2e && npm test` (against `docker compose up`)
- Build: `cd frontend && npm run build`
- Config comes from environment variables; see the three `.env.example` files and `docs/configuration.md`. Never commit secrets.

## Where things are

- `backend/app/api/`: HTTP layer split into `routers/` → `mediators/` → `services/`, plus provider `configs/`.
- `backend/app/core/`: settings, security, logging, LLM client (OpenRouter), PostHog, rate limiting, the billing gateway (the only Stripe SDK user).
- `backend/app/db/`, `backend/alembic/`: SQLAlchemy models, sessions, migrations.
- `frontend/src/`: `pages/` (routes), `features/` (self-contained modules), `components/`, `services/` (API clients), `lib/`.
- `e2e/`: Playwright smoke tests. `infra/`, `scripts/deploy.sh`, `docs/deployment.md`: single-server deploy.
- `docs/development.md`: project layout and recipes (Subscriptions, LLM calls, analytics events, branding).

## Rules

- Use the domain language in `GLOSSARY.md`. Read ADRs in `docs/adr/` before changing an area, and flag contradictions instead of silently overriding them.
- Work on a branch and open a PR that follows `.github/pull_request_template.md`. Never push to `main`.
- Coding standards live in `CODING_STANDARDS.md` and are checked at review time.
- Backend call direction is `router → mediator → service`, never backwards. No DB queries in routers or mediators.
- Stripe webhook handlers never commit: `mediators/billing.handle_webhook` owns the transaction; raise to roll back.
- Frontend: storage keys and lock names go through `src/lib/storage.ts` / `APP_SLUG`; every analytics event is declared in `EVENTS` (`src/lib/analytics.ts`); token refreshes go only through `performRefresh()` in `src/services/apiService.ts`.

## Agent skills

### Issue tracker

Issues live in GitHub Issues on `pumpkit-io/pumpkit`, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: one root `GLOSSARY.md` plus `docs/adr/`. See `docs/agents/domain.md`.
