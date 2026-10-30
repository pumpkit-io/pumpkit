# CI calls these targets (.github/workflows/ci.yml), so a target that passes here passes there.
DEV_COMPOSE ?= docker compose -f compose.dev.yml
# The production stack; pass COMPOSE="docker compose -p NAME" to run it beside another one.
COMPOSE ?= docker compose
SMOKE_URL ?= http://localhost:8080
# The app e2e runs against; scripts/dev-stack's Dev URL for a worktree's own stack.
E2E_BASE_URL ?= http://localhost:5173

.PHONY: dev check check-backend check-frontend check-e2e test test-backend test-frontend fmt e2e e2e-wait smoke

dev:
	$(DEV_COMPOSE) up --build

check: check-backend check-frontend check-e2e

check-backend:
	cd backend && uv run ruff check .
	cd backend && uv run ruff format --check .
	cd backend && uv run --extra dev pyright
	cd backend && uv run --extra dev lint-imports

check-frontend:
	cd frontend && npm run lint
	cd frontend && npm run format:check
	cd frontend && npm run typecheck
	cd frontend && npm run build

check-e2e:
	cd e2e && npm run format:check
	cd e2e && npm run typecheck

test: test-backend test-frontend

test-backend:
	cd backend && uv run --extra dev pytest

test-frontend:
	cd frontend && npm test

fmt:
	cd backend && uv run ruff format .
	cd frontend && npm run format
	cd e2e && npm run format

# Starts the dev stack in the background if it is not already up, and leaves it running.
e2e:
	$(DEV_COMPOSE) up -d --build
	$(MAKE) e2e-wait
	cd e2e && npm test

e2e-wait:
	@for url in $(E2E_BASE_URL)/api/v1/health $(E2E_BASE_URL); do \
		tries=0; \
		until curl -sf -o /dev/null $$url; do \
			tries=$$((tries + 1)); \
			if [ $$tries -ge 90 ]; then echo "Timed out waiting for $$url" >&2; exit 1; fi; \
			sleep 2; \
		done; \
	done

# Builds and starts the production stack from this checkout's .env, then checks it over HTTP.
# The checks expect the PostHog relay exactly when the running web service has it turned on.
smoke:
	$(COMPOSE) up -d --build --wait --wait-timeout 300
	POSTHOG_RELAY=$$($(COMPOSE) exec -T web printenv POSTHOG_RELAY) sh scripts/check-stack.sh $(SMOKE_URL)
