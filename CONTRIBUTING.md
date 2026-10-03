# Contributing to Pumpkit

Thanks for helping! Pumpkit is in early development, so expect things to move.

## Development setup

Prerequisites: Docker with Compose, Node.js 22 or newer with npm, and [uv](https://docs.astral.sh/uv/) (it installs the Python version in `backend/.python-version`).

```bash
# Environment: copy the three example files, then fill in the values (see docs/configuration.md)
cp .env.example .env && cp backend/.env.example backend/.env && cp frontend/.env.example frontend/.env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"          # JWT_SECRET_KEY, POSTGRES_PASSWORD
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # FERNET_ENCRYPTION_KEY

# Run everything (Postgres, backend on :8000, frontend on :5173)
docker compose up --build

# Local tooling for tests, linting and the pre-commit hook
npm install                                   # repo root: installs the Husky pre-commit hook
(cd frontend && npm install) && (cd e2e && npm install)
(cd backend && uv sync --extra dev)
```

Checks before you push:

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run --extra dev pyright && uv run --extra dev pytest
cd frontend && npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
```

The project layout and common recipes are in [docs/development.md](./docs/development.md).

## How work flows

- **Bugs and feature requests:** open an issue using the templates. New issues get `needs-triage`; a maintainer moves them to `needs-info`, `ready-for-agent`, `ready-for-human` or `wontfix`.
- **`ready-for-agent` issues** are fully specified, with acceptance criteria and blocking links. They are the best place to start, whether you code by hand or with an agent.
- **Non-trivial changes:** open or comment on an issue before writing code, so we agree on the approach first.

## Pull requests

- Branch from `main`; one logical change per PR; link the issue (`Closes #N`).
- Fill in the PR template: a small summary visual, before/after evidence (a screenshot or test output), and the merge danger.
- CI (lint, format, typecheck, tests) must pass.
- Domain terms come from `GLOSSARY.md`; architectural decisions live in `docs/adr/`; review standards are in `CODING_STANDARDS.md`.

## AI-assisted contributions

Welcome. You are responsible for every line you submit, and the evidence section of the PR is how you show it works. Most coding agents read `AGENTS.md` automatically.

## Optional: the maintainer's agent workflow

This repo is developed with [pumpkit-io/sdlc](https://github.com/pumpkit-io/sdlc), a set of agent skills for the issue-to-spec-to-PR flow. You don't need it to contribute. To use it:

- Claude Code: `claude plugin marketplace add pumpkit-io/sdlc` then `claude plugin install sdlc@pumpkit-io`
- Codex and other agents: `npx skills@latest add pumpkit-io/sdlc`

This repo's configuration for it is already in `docs/agents/`.

## License

By contributing, you agree that your contributions are licensed under the project's license (see `LICENSE`).
