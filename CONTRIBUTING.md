# Contributing to Pumpkit

Thanks for helping! Pumpkit is in early development, so expect things to move.

## Development setup

Prerequisites: Docker with Compose, Make, Node.js 22 or newer with npm, and [uv](https://docs.astral.sh/uv/) (it installs the Python version in `backend/.python-version`).

```bash
# Environment: writes .env with the secrets generated (see docs/configuration.md).
# Placeholder keys are enough until you write a Post or add an Inspiration author.
LLM_API_KEY=dev TWITTERAPI_IO_API_KEY=dev sh scripts/setup.sh --public-url http://localhost:5173 </dev/null

# Local tooling for checks, tests and the Git hooks
npm install                                   # repo root: installs the Husky pre-commit and pre-push hooks
(cd frontend && npm install) && (cd e2e && npm install && npx playwright install chromium)
(cd backend && uv sync --extra dev)

# Run everything with hot reload: Postgres, the backend on :8000, the publisher, and the app on :5173
make dev
```

`make dev` runs the stack in `compose.dev.yml`, which bind-mounts `backend/` and `frontend/` and sets `PUBLIC_URL` to `http://localhost:5173`. Open the app at http://localhost:5173 and the API docs at http://localhost:8000/docs. Without SMTP, Magic links go to the backend log (`docker compose -f compose.dev.yml logs backend | grep "Magic link for"`). To add a real key later, edit its line in `.env`: `setup.sh` keeps values already there.

### Make targets

CI runs these same targets, so a branch that passes them locally passes CI.

| Target       | What it runs                                                                                              |
| ------------ | --------------------------------------------------------------------------------------------------------- |
| `make dev`   | The dev stack in `compose.dev.yml`, in the foreground                                                     |
| `make check` | Lint, format check, typecheck and import contracts for backend, frontend and e2e, plus the frontend build |
| `make test`  | Backend pytest and frontend vitest                                                                        |
| `make fmt`   | The formatters in all three packages (ruff format and Prettier)                                           |
| `make e2e`   | Starts the dev stack in the background if it is down, waits for it, then runs Playwright against it       |

Each package also has its own targets: `check-backend`, `check-frontend`, `check-e2e`, `test-backend` and `test-frontend`. Run `make check test` before you push.

The e2e suite checks Plan and Usage in Settings, so `make e2e` needs the Stripe billing group in `.env`. Dummy values work: `STRIPE_SECRET_KEY=sk_test_dummy`, `STRIPE_PUBLISHABLE_KEY=pk_test_dummy`, `STRIPE_WEBHOOK_SECRET=whsec_dummy` and `BILLING_PLAN_KEYS='["pumpkit_pro_monthly"]'`, plus `BILLING_TOP_UP_KEY=pumpkit_top_up`. Set `GENERATIONS_MONTHLY_CAP=500`, `X_POSTS_MONTHLY_CAP=100` and `X_LINK_POSTS_MONTHLY_CAP=10`. The usage tests seed a separate User before each test and stub the Stripe-backed catalog response; usage and generation refusals come from the backend. Purchase dialogs are cancelled before payment. Use only dummy billing credentials.

### Stripe webhooks

To try billing against Stripe in test mode, put your test keys in `.env` and forward webhooks to the dev backend with the [Stripe CLI](https://docs.stripe.com/stripe-cli):

```bash
stripe listen --forward-to localhost:8000/api/v1/stripe/webhook
```

Use the `whsec_...` secret it prints as `STRIPE_WEBHOOK_SECRET`, then restart the backend so it reads the new value.

The project layout and common recipes are in [docs/development.md](./docs/development.md).

## How work flows

- **Bugs and feature requests:** open an issue using the templates. New issues get `needs-triage`; a maintainer moves them to `needs-info`, `ready-for-agent`, `ready-for-human` or `wontfix`.
- **`ready-for-agent` issues** are fully specified, with acceptance criteria and blocking links. They are the best place to start, whether you code by hand or with an agent.
- **Non-trivial changes:** open or comment on an issue before writing code, so we agree on the approach first.

## Pull requests

- Branch from `main`; one logical change per PR; link the issue (`Closes #N`).
- Fill in the PR template: a small summary visual, before/after evidence (a screenshot or test output), and the merge danger.
- Add a line under `## [Unreleased]` in `CHANGELOG.md` saying what changes for Users or Self-hosters, with **Upgrade notes:** for any manual upgrade step. A change nobody running or using an Instance would notice (tests, refactors, CI, contributor docs) gets the `no-changelog` label instead.
- CI (lint, format, typecheck, tests, the CHANGELOG check) must pass.
- A maintainer runs the LLM review (the required `review` check) by hand once the PR is ready, and again after later pushes.
- Domain terms come from `GLOSSARY.md`; architectural decisions live in `docs/adr/`; review standards are in `CODING_STANDARDS.md`.

## Releases

Maintainers cut releases by pushing a version tag; [docs/releasing.md](./docs/releasing.md) has the steps.

## AI-assisted contributions

Welcome. You are responsible for every line you submit, and the evidence section of the PR is how you show it works. Most coding agents read `AGENTS.md` automatically.

## Optional: the maintainer's agent workflow

This repo is developed with [pumpkit-io/sdlc](https://github.com/pumpkit-io/sdlc), a set of agent skills for the issue-to-spec-to-PR flow. You don't need it to contribute. To use it:

- Claude Code: `claude plugin marketplace add pumpkit-io/sdlc` then `claude plugin install sdlc@pumpkit-io`
- Codex and other agents: `npx skills@latest add pumpkit-io/sdlc`

This repo's configuration for it is already in `docs/agents/`.

## License

By contributing, you agree that your contributions are licensed under the project's license (see `LICENSE`).
