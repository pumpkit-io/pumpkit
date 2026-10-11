# Backend packages by domain area

The backend is one installable package, `src/pumpkit/`, with tests outside it in `backend/tests/`. The package is split by domain area instead of by layer: `auth`, `billing`, `authors`, `posts`, `x_connection`, `scheduling` and `support`. Each area holds its own `router.py`, `mediator.py`, `service.py`, `schemas.py` and `models.py`, plus the adapter for the provider it owns: Stripe in `billing`, twitterapi.io in `authors`, X's API in `x_connection`, the LLM endpoint in `posts`. `core` keeps only the plumbing every area shares: config, logging, the database session, errors, security, rate limiting, analytics, time and ids. The layer-first layout spread one feature across five directories and left `core` with 20 unrelated modules. It also made `publishing/` import the API layer, which in turn imported `publishing/` back.

## Rules

- Router → mediator → service still holds inside each area.
- An area skips the modules it has no use for: `support` has nothing to orchestrate or store, so it has only a router and the schemas of its responses.
- A module that would grow unwieldy may become a subpackage, as `auth/service/` did.
- An area may import another area's `service`, `models`, `schemas` and domain modules, never its `router` or `mediator`.
- Areas never import in a cycle. The order is `core` ← `auth` ← `billing` ← {`authors`, `x_connection`, `support`} ← `posts` ← `scheduling`.
- `GET /x-connection` and `POST /x-connection/authorizations/complete` are served from `scheduling`, not `x_connection`: their response carries the count of waiting Scheduled posts, and `x_connection` may not import `scheduling`.
- `core` imports no area. Errors that map to an HTTP response subclass a base error in `core`, so one generic handler answers them all.
- `User` has no relationships to other areas' models. Each child keeps its `user` relationship and its `ON DELETE CASCADE` foreign key, and `pumpkit/models.py` imports every area's models so Alembic and the tests see the whole schema.
- import-linter enforces the import rules in CI.

Since ADR 0011 made providers optional, `support` has `schemas.py` for the `/instance` response, and `posts` calls any OpenAI-compatible LLM endpoint, OpenRouter by default.

## Considered Options

- **Layer-first, with `core` split into subpackages.** The smallest change, but each feature stays spread across `routers/`, `mediators/`, `services/`, `schemas/` and `db/`.
- **Layered `api/`, with pure domain logic in domain packages and the adapters in an `integrations/` package.** This fixes `core`, but a contributor still has to look in three places for one feature, and `integrations/` turns into a grab-bag of its own.
- **One package per glossary section (`accounts`, `billing`, `writing`, `publishing`).** The names match GLOSSARY.md, but two of those packages would need a second level of nesting to hold two routers each.
