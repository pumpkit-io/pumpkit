# Pumpkit

Open-source AI writing tool for X: turns a brief into a post written in the style of X authors you choose, then revises it with your feedback.

## Stack and commands

- Backend: Python 3.13, FastAPI, SQLAlchemy, Alembic, managed with **uv** (`backend/`). Frontend: React, Vite, TypeScript, Tailwind, managed with **npm** (`frontend/`). E2E: Playwright, npm (`e2e/`).
- Root `Makefile`, which CI calls: `make check` (lint, format check, typecheck, import contracts and frontend build, all three packages) · `make test` (backend and frontend) · `make fmt` · `make e2e` (starts the dev stack if needed) · `make dev`. Per package: `make check-backend`, `check-frontend`, `check-e2e`, `test-backend`, `test-frontend`. The per-package commands below are what they run.
- Dev: `make dev`, or `docker compose -f compose.dev.yml up --build` (Postgres, backend on :8000, frontend on :5173, which proxies `/api` to the backend)
- Lint: `cd backend && uv run ruff check .` · `cd frontend && npm run lint`
- Format: `cd backend && uv run ruff format .` · `cd frontend && npm run format` (same in `e2e/`)
- Imports: `cd backend && uv run --extra dev lint-imports` (ADR 0008's package rules, contracts in `backend/pyproject.toml`)
- Typecheck: `cd backend && uv run --extra dev pyright` · `cd frontend && npm run typecheck` (same in `e2e/`)
- Test: `cd backend && uv run --extra dev pytest` (SQLite, no services needed) · `cd frontend && npm test` · `cd e2e && npm test` (against the `compose.dev.yml` stack)
- Build: `cd frontend && npm run build`
- Config comes from one root `.env`, written by `sh scripts/setup.sh` from `.env.example`; every URL derives from `PUBLIC_URL`. See `docs/configuration.md`. Never commit secrets.
- To self-host Pumpkit, follow `docs/self-hosting.md`.

## Where things are

- `backend/src/pumpkit/`: one package per domain area (ADR 0008): `auth`, `billing`, `authors`, `posts`, `x_connection`, `scheduling`, `support`. Each holds `router.py`, `mediator.py`, `service.py`, `schemas.py` and `models.py` (`support` has only a router and schemas), plus the adapter for the provider it owns: `billing/gateway.py` (the only Stripe SDK user), `authors/x_reader.py` (twitterapi.io, ADR 0005), `x_connection/x_publisher.py` (X's own API for connecting accounts and publishing, ADR 0006), `posts/llm.py` (the LLM port over structured calls to an OpenAI-compatible endpoint).
- `backend/src/pumpkit/core/`: plumbing every area shares (config, logging, `db/` session and base, errors, security, rate limiting, analytics, time, ids, and `mcp_tools.py`, how MCP tools are declared and their errors answered), plus `classifier.py`, the classifier port over Jev, TypeSafe's hosted classifier, which no single area owns (ADR 0013). `main.py` mounts every router and the MCP endpoint; `models.py` imports every area's models for Alembic and the tests.
- MCP server (ADR 0012): each area's MCP tools live in its `tools.py`, beside `router.py`, and call only that area's mediator (`authors/tools.py`; `posts`, `scheduling` and `billing` have one too). Tools that need a browser, such as `connect_x` and `manage_subscription`, only answer with a web app link. `mcp_server.py`, next to `main.py`, is the one assembly point: it builds the server from every `TOOLS` list and the server instructions, authenticates API keys, gates and limits each tool, and serves `POST /api/v1/mcp`. Recipe in `docs/development.md`, user guide in `docs/claude-code.md`.
- Writing: `posts/writing/` holds the pumpkit-v6 workflow (prompts as plain text, corpus framing, scrub, and writing a Version: sketch or revision call, which writes the Hook too, scrub, humanizer call). `posts/version_writing.py` adds a Version from Feedback. The `authors` and `posts` areas serve Inspiration authors and Posts.
- Post status (ADR 0015): a Post has at most one Scheduled post and takes its status from it (`scheduling/post_status.py`), so `GET /posts`, `GET /posts/{id}` and `POST /posts/{id}/versions` (the Feedback gate) live in `scheduling/router.py`, and the `list_posts`, `get_post` and `give_feedback` tools in `scheduling/tools.py`.
- Publishing: `scheduling/` publishes Scheduled posts at most once (ADR 0007). `publishing.py` sequences and commits a publish for both Post now and the publisher, over the flush-only steps in `publish.py`; `publisher.py` is the publisher process's pass, loop and entry point, run as `python -m pumpkit.scheduling.publisher` (its own compose service).
- Frontend pages: routes in `pages/signedInRoutes.tsx`, inside `pages/AppLayout.tsx`. New post, the Posts tabs (`features/posts/list/`) and each Post's page (panels, "Post to…" and inline edit in `features/posts/panels/`, `postTo/`, `edit/`), Persona (`features/inspirationAuthors/`) and Settings (one card per feature: billing, account, xConnection, apiKeys, theme). `features/scheduledPosts/` holds what they share about Scheduled posts. Page map in `docs/development.md`.
- X connection routes: `x_connection/router.py` starts an authorization and disconnects; `GET /x-connection` and `POST /x-connection/authorizations/complete` live in `scheduling/router.py` because they answer with the count of waiting Scheduled posts, and `x_connection` sits below `scheduling`.
- `backend/alembic/`: migrations.
- `backend/tests/`: the pytest suite, mirroring the package tree, with shared fixtures in `conftest.py`.
- `frontend/src/`: `pages/` (routes), `features/` (self-contained modules), `components/`, `services/` (API clients), `lib/`.
- `e2e/`: Playwright smoke tests, against the dev stack in `compose.dev.yml`.
- Self-hosting: `compose.yml` (the production stack), `compose.external-db.yml`, `infra/web/` (the web image: Caddy serving the built frontend), `scripts/setup.sh` (writes `.env`), `scripts/check-stack.sh` (smoke checks).
- Releasing and deploying: cut a release only by following `docs/releasing.md` step by step (`scripts/prepare-release.sh`, `scripts/tag-release.sh`, `.github/workflows/release.yml`). Deploying pumpkit.io follows `deploy.md` in the private `pumpkit-io/pumpkit-ops`, cloned at `../pumpkit-ops`.
- `docs/development.md`: project layout and recipes (Subscriptions, Scheduled posts, LLM calls, analytics events, branding).

## Rules

- Use the domain language in `GLOSSARY.md`. Read ADRs in `docs/adr/` before changing an area, and flag contradictions instead of silently overriding them.
- Work on a branch and open a PR that follows `.github/pull_request_template.md`. Never push to `main`.
- Every PR adds a line under `## [Unreleased]` in `CHANGELOG.md` saying what changes for Users or Self-hosters, with **Upgrade notes:** for any manual step an upgrade needs; a PR nobody running or using an Instance would notice gets the `no-changelog` label instead. CI checks it.
- Coding standards live in `CODING_STANDARDS.md` and are checked at review time.
- Backend call direction is `router → mediator → service`, never backwards. No DB queries in routers or mediators. Across areas, import only another area's service, models, schemas and domain modules, in ADR 0008's area order.
- Stripe webhook handlers never commit: `billing/mediator.handle_webhook` owns the transaction; raise to roll back.
- Frontend: storage keys and lock names go through `src/lib/storage.ts` / `APP_SLUG`; every analytics event is declared in `EVENTS` (`src/lib/analytics.ts`); token refreshes go only through `performRefresh()` in `src/services/apiService.ts`.

## Agent skills

### Issue tracker

Issues live in GitHub Issues on `pumpkit-io/pumpkit`, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: one root `GLOSSARY.md` plus `docs/adr/`. See `docs/agents/domain.md`.

### PR review

The required `review` check runs the `review-changes` skill on Claude Code, from `.github/workflows/sdlc-review-llm.yml`. It never runs on its own: a repository admin starts it on a PR's branch, and so can an agent whose `gh` is logged in as one, when the user asks. Start it with `gh workflow run sdlc-review-llm.yml --ref <branch>` and follow it with `gh run watch`; the verdict lands as a PR comment. It reviews the branch's head commit, so run it again after every push.

### Code comments

Load the `code-comments` skill before writing or editing any comment.

### Worktrees

Never edit files or commit in the main checkout, even for a one-line change. Before your first file change or commit, load the `worktrees` skill and resolve a worktree for the work, then work and commit there. Release its lock when the work is committed. The one exception is a main-checkout path a skill names, such as `improve-codebase-architecture`'s notes.

### Dev stack

Start, check and stop the app only through `scripts/dev-stack`: load the `dev-stack` skill when you need it running. See `docs/agents/dev-stack.md`.
