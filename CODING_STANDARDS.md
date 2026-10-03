# Coding standards

Read by reviewers (human and the code-review skill) when reviewing a diff. Only judgement calls belong here: anything a linter, formatter, type checker or test can enforce goes into tooling instead.

- Name domain concepts with the terms in `GLOSSARY.md`; don't introduce synonyms it lists under _Avoid_.
- Validate external input at the boundary (API routes, webhooks, queue consumers, third-party API responses), then trust typed data inside. Convert Stripe SDK objects to dicts with `.to_dict()` at that boundary (stripe-python 15+ objects have no `.get()`).
- Keep side effects (X API, Telegram, LLM calls, database) at the edges behind small interfaces; keep decision logic pure and testable.
- Test behaviour through public interfaces, not internals. A refactor that keeps behaviour should not break tests.
- A new dependency needs a one-line reason in the PR body.
- Never log secrets, tokens or full API payloads that may contain them.
- Prefer small, focused functions and modules with one clear responsibility; don't mix unrelated concerns in one file.
- Backend: add a mediator only when there is real orchestration (locks, caching, multi-service coordination); a pure pass-through router may call a service directly.
- Python imports go at the top of the file. A circular import is a structural problem: split the module or extract a leaf module instead of importing inside a function.
- Python optional values use `Optional[X]` from `typing`, not `X | None`, matching the existing code.
