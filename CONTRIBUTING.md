# Contributing to Pumpkit

Thanks for helping! Pumpkit is in early development, so expect things to move.

## Development setup

Prerequisites: Docker with Compose, Make, Node.js 22 or newer with npm, and [uv](https://docs.astral.sh/uv/) (it installs the Python version in `backend/.python-version`).

```bash
# Environment: writes .env with the secrets generated (see docs/configuration.md).
# Placeholder keys are enough until you write a Post or add an Inspiration author.
X_CLIENT_ID=dev X_CLIENT_SECRET=dev LLM_API_KEY=dev TWITTERAPI_IO_API_KEY=dev sh scripts/setup.sh --public-url http://localhost:5173 </dev/null

# Local tooling for checks, tests and the Git hooks
npm install                                   # repo root: installs the Husky pre-commit and pre-push hooks
(cd frontend && npm install) && (cd e2e && npm install && npx playwright install chromium)
(cd backend && uv sync --extra dev)

# Run the isolated stack with hot reload and local provider stand-ins
scripts/dev-stack up
```

Use `scripts/dev-stack up` for isolated local work. It prints this worktree's Dev URL, starts provider stand-ins with throwaway credentials, and disables external publishing, email and analytics. Check and stop it through the same contract; see [the dev stack guide](docs/agents/dev-stack.md). The normal Dev URL signs in through the deterministic local X provider. No live X or mail credentials are needed for browser authentication tests. Google and magic link implementations remain inactive; there is no method-selection setting.

### Make targets

CI runs these same targets, so a branch that passes them locally passes CI.

| Target              | What it runs                                                                                              |
| ------------------- | --------------------------------------------------------------------------------------------------------- |
| `make dev`          | The isolated emulated dev stack through `scripts/dev-stack up`                                            |
| `make dev-personal` | Personal localhost stack with real X and Stripe sandbox                                                   |
| `make check`        | Lint, format check, typecheck and import contracts for backend, frontend and e2e, plus the frontend build |
| `make test`         | Backend pytest and frontend vitest                                                                        |
| `make fmt`          | The formatters in all three packages (ruff format and Prettier)                                           |
| `make e2e`          | Starts the dev stack in the background if it is down, waits for it, then runs Playwright against it       |

Each package also has its own targets: `check-backend`, `check-frontend`, `check-e2e`, `test-backend` and `test-frontend`. Run `make check test` before you push.

The contract supplies the dummy Stripe billing group and Top-up key for browser tests; do not add live billing credentials for this purpose. Set `GENERATIONS_MONTHLY_CAP=500`, `X_POSTS_MONTHLY_CAP=100` and `X_LINK_POSTS_MONTHLY_CAP=10` in `.env`. Usage tests seed their own X-identified User and stub the catalog response. Real Checkout interactions run only against the isolated Stripe stand-in.

### Stripe webhooks

For personal testing with real X and Stripe's sandbox, use a dedicated worktree
and `make dev-personal`. Configure its sandbox catalog, keys and webhook listener
as described in [Personal testing on localhost](docs/agents/dev-stack.md#personal-testing-on-localhost-with-real-providers).
Open `http://localhost:5173`; register `http://127.0.0.1:5173/oauth/x/callback` on X.
The dev server relays that callback back to localhost before login completes.

The default `make dev` and agent stacks keep using provider stand-ins and their
own data. Existing `--real-x` stacks retain their separate data and emulated Stripe.

The project layout and common recipes are in [docs/development.md](./docs/development.md).

## How work flows

- **Bugs and feature requests:** open an issue using the templates. New issues get `needs-triage`; a maintainer moves them to `needs-info`, `ready-for-agent`, `ready-for-human` or `wontfix`.
- **`ready-for-agent` issues** are fully specified, with acceptance criteria and blocking links. They are the best place to start, whether you code by hand or with an agent.
- **Non-trivial changes:** open or comment on an issue before writing code, so we agree on the approach first.

## Pull requests

- Branch from `main`; one logical change per PR; link the issue (`Closes #N`).
- Fill in the PR template: a small summary visual, before/after evidence (a screenshot or test output), and the merge danger.
- Add a line under `## [Unreleased]` in `CHANGELOG.md` saying what changes for Users or Self-hosters, with **Upgrade notes:** only for a manual upgrade step (a new required setting in `.env.example`, a changed compose file, a destructive migration, a default that changes behavior unless a setting is set). An entry with nothing to do by hand says so in its prose and carries no Upgrade notes; CI rejects Upgrade notes that say there is nothing to do. A change nobody running or using an Instance would notice (tests, refactors, CI, contributor docs) gets the `no-changelog` label instead.
- CI (lint, format, typecheck, tests, the CHANGELOG check) must pass.
- A maintainer runs the LLM review (the required `review` check) by hand once the PR is ready, and again after later pushes.
- Domain terms come from `GLOSSARY.md`; architectural decisions live in `docs/adr/`; review standards are in `CODING_STANDARDS.md`.

## Releases

Maintainers cut releases only with `sh scripts/release.sh`; [docs/releasing.md](./docs/releasing.md) has the steps.

## AI-assisted contributions

Welcome. You are responsible for every line you submit, and the evidence section of the PR is how you show it works. Most coding agents read `AGENTS.md` automatically.

## Optional: the maintainer's agent workflow

This repo is developed with [pumpkit-io/sdlc](https://github.com/pumpkit-io/sdlc), a set of agent skills for the issue-to-spec-to-PR flow. You don't need it to contribute. To use it:

- Claude Code: `claude plugin marketplace add pumpkit-io/sdlc` then `claude plugin install sdlc@pumpkit-io`
- Codex and other agents: `npx skills@latest add pumpkit-io/sdlc`

This repo's configuration for it is already in `docs/agents/`.

## License

By contributing, you agree that your contributions are licensed under the project's license (see `LICENSE`).
