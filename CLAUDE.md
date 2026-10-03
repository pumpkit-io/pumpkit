# Project guidelines for Claude Code

## General

- Write clean, modular code. Prefer small, focused functions and modules. Keep responsibilities clear; avoid mixing unrelated concerns in one file or function.

## Backend (Python — `backend/`)

### Imports

- All `import` statements MUST be at the top of the file. No imports inside functions, methods, or conditional branches.
- If top-level imports trigger a circular-import error, treat that as a structural problem: split the module, extract shared types/constants into a leaf module, or move one side of the dependency. Do NOT work around it with a function-local import.

### Stripe SDK objects

- Convert Stripe SDK return objects to dicts with `.to_dict()` at the boundary; stripe-python 15+ objects have no `.get()`.

### Optional types

- For optional values, use `Optional[X]` from `typing`, not `X | None`.
  - Example: `def get_user(user_id: str) -> Optional[User]: ...`
- This matches the existing convention across `backend/app/` (see `backend/app/api/services/purchases.py`, `backend/app/api/routers/billing.py`).

### API endpoint layering

HTTP endpoints under `backend/app/api/` follow a three-layer split. Preserve each layer's responsibility when adding or modifying endpoints.

- `routers/` — FastAPI route definitions only. Auth dependencies, request parsing, response shaping, and HTTP error translation. No business logic and no direct DB queries here.
- `mediators/` — orchestration. Coordinates one or more services and handles cross-cutting concerns (locks, caching, streaming, tracing). Returns domain results to the router.
- `services/` — single-responsibility units that own one resource or capability (DB access, external API calls, encryption, etc.).

The only hard rule is the call direction: `router → mediator → service`. Calls must never flow backwards.

- A `router` may call a `mediator` **or** a `service` directly.
- A `mediator` may call a `service`, but never a `router`.
- A `service` may call neither a `router` nor a `mediator`.

Prefer routing through a mediator whenever there is real orchestration (locks, caching, multi-service coordination, cross-cutting concerns). When an endpoint is a pure pass-through with no such logic, the router may call the service directly rather than introduce a mediator that adds nothing. Do not put DB queries in a router or a mediator.

Reference flow: `routers/billing.py` → `mediators/purchases.py` → `services/purchases.py`. Direct router → service is fine for trivial reads (e.g. `routers/billing.py` listing purchases via `services/purchases.py`).

### Stripe webhooks

- `mediators/stripe.handle_webhook` deduplicates every event in `stripe_events` and runs the handler in ONE transaction that it commits. Handlers and hooks must never commit; raise to roll back and let Stripe retry.

## Frontend (`frontend/`)

- Browser storage keys and lock names go through `src/lib/storage.ts` / `APP_SLUG` — never hardcode an app-name prefix.
- Every analytics event must be declared in `EVENTS` (`src/lib/analytics.ts`).
- All token refreshes go through `performRefresh()` in `src/services/apiService.ts`; never call `/refresh-token` directly.

## Tests

- Backend: `cd backend && uv run --extra dev pytest` (SQLite test DB; fixtures in `app/tests/conftest.py`).
- Frontend: `cd frontend && npm test && npm run build`.
- E2E: `cd e2e && npm test` against `docker compose up`.
