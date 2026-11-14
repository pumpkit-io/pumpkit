# Local personal Compose implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan in the current session.

**Goal:** Plain Compose runs personal testing on localhost with no DEV_* settings; agents keep isolated emulated stacks.

**Architecture:** Move relay defaults into base Compose and override them in the emulator assembly. Validate personal provider settings at backend startup, before serving or publishing. Simplify the agent launcher to its emulated path.

**Tech stack:** Docker Compose, Bash, Python Settings, Vite.

**Spec:** docs/adr/0029-local-compose-is-for-personal-testing.md

## Global constraints

- Preserve pumpkit-dev project and volume names; never migrate or delete old mode data.
- Preserve current main's seller mode and production configuration.
- Default localhost:5173 without DEV_PUBLIC_URL or DEV_PUBLIC_PORT.
- Agent operations use scripts/dev-stack; human operations may use plain Compose.

## Review focus

- Missing billing stays supported; mixed or live Stripe credentials fail locally.
- Inherited relay settings must not break generated agent origins or the staged fixture.
- Old saved mode state and flags fail before touching Docker or routes.
- IPv4 and IPv6 localhost resolve to the same frontend; E2E refuses personal targets.
- Agent projects must never select the personal project's volumes.

### Task 1: Personal Compose and provider validation

Files: compose.dev.yml, compose.emulators.yml, backend/src/pumpkit/core/config.py, scripts/tests/test_dev_stack.py, backend/tests/core/test_config.py.

- [x] Change existing rendered-Compose tests to assert default personal origin, relay wiring, loopback ports, persistent volume names and configured publishing with DEV_* absent. Assert emulator origin/credentials and relay disabled for all services.
- [x] Add Settings tests for local personal sandbox credentials, absent billing, rejected live credentials and provider overrides; retain production behavior.
- [x] Run python3 scripts/tests/test_dev_stack.py and uv run --extra dev pytest tests/core/test_config.py; observe failures before implementation.
- [x] Move relay and frontend defaults into Compose; override ports and relay in emulator assembly. Add startup provider validation at the existing personal-relay Settings boundary.
- [x] Re-run targeted tests and typechecking.

### Task 2: One agent startup path

Files: scripts/dev-stack, scripts/tests/test_dev_stack.py, compose.personal.yml, compose.real-x.yml, scripts/check-personal-stack.py, Makefile.

- [x] Replace removed-mode tests with CLI tests for emulated lifecycle, explicit retired-flag rejection and refusal of saved personal/real-x state without Docker or route actions.
- [x] Observe failures, then remove mode implementations, redundant override files, obsolete validator and dev-personal target. Refuse agent launcher in main checkout to protect the shared personal project.
- [x] Run CLI/Compose tests, relay tests and E2E safety tests.

### Task 3: Documentation and verification

Files: AGENTS.md, CONTRIBUTING.md, docs/agents/dev-stack.md, docs/development.md, docs/configuration.md, CHANGELOG.md and remaining current startup references.

- [x] Document plain Compose defaults, X callback registration, Stripe listener, sandbox-only billing, optional custom port settings, retained volume recovery and separate agent workflow.
- [x] Run make check and make test, then start this worktree's emulated stack through scripts/dev-stack and verify protocol smoke at its generated URL.
- [ ] Review Standards, Spec and Correctness against origin/main and the ADR; fix blockers, commit, push once and open PR. Run required admin review and report its result.
