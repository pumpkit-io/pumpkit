# Coding standards

Read by reviewers (human and the code-review skill) when reviewing a diff. Only judgement calls belong here: anything a linter, formatter, type checker or test can enforce goes into tooling instead.

- Name domain concepts with the terms in `GLOSSARY.md`; don't introduce synonyms it lists under _Avoid_.
- Validate external input at the boundary (API routes, webhooks, queue consumers, third-party API responses), then trust typed data inside. Convert Stripe SDK objects to dicts with `.to_dict()` at that boundary (stripe-python 15+ objects have no `.get()`).
- Keep side effects (twitterapi.io, LLM calls, database) at the edges behind small interfaces; keep decision logic pure and testable.
- Test behaviour through public interfaces, not internals. A refactor that keeps behaviour should not break tests.
- A new dependency needs a one-line reason in the PR body.
- Never log secrets, tokens or full API payloads that may contain them. One exception: on an Instance without SMTP, `LogAuthMailer` logs each Magic link, because the log is where that Instance delivers it (ADR 0011).
- Prefer small, focused functions and modules with one clear responsibility; don't mix unrelated concerns in one file.
- Backend: add a mediator only when there is real orchestration (locks, caching, multi-service coordination); a pure pass-through router may call a service directly.
- Backend: the mediator owns the database transaction and commits once per request. Services, hooks and domain modules `flush` and never `commit`. For a pass-through route with no mediator, the router does that single commit. One allowed early commit persists the result of an external side effect before the next external call, for example a newly created Stripe customer before checkout, or a magic-link row before its email is sent. A mediator may also commit to end its read transaction before a long external call, so no connection stays held across it, and to keep the record of a failed external call before re-raising, since the request session rolls back on any exception. For the same reason, it may commit evidence that must outlive a failed external call before making that call, for example a User's acceptance of the Terms before Stripe Checkout. Mark each early commit with a comment saying why.
- Backend: a provider adapter (a port and its implementations, such as the billing gateway or the X publisher) lives in the area that owns the provider, not in `core` or a shared package. Another area that needs the provider imports it from there.
- Backend: an area's public surface is its service, models, schemas and domain modules (rules, dependencies, adapters). Reuse them from the owning area instead of copying a schema or helper into yours.
- Python imports go at the top of the file. A circular import is a structural problem: split the module or extract a leaf module instead of importing inside a function.
- Python optional values use `Optional[X]` from `typing`, not `X | None`, matching the existing code.
