# Dev stack

- Entry point: `scripts/dev-stack`
- Strategy: B
- Project: `pumpkit`
- Health URL: `/api/v1/health`
- e2e: `cd e2e && npm test`
- Cap: 10
- Portless: 0.15.12
- Proxy: HTTP on 1355

## Safe mode

- `PUBLISHER_ENABLED=false`: the publisher process runs but publishes nothing to X.
- `SMTP_HOST=` and `EMAIL_FROM=`: Magic links are logged instead of emailed. Blanking only one leaves SMTP partly configured, and the backend refuses to start.
- `POSTHOG_ENABLED=false`: the backend sends no analytics events.

## E2E data

Use `e2e/backend.ts` to run scripts from `e2e/seed/` inside this worktree's backend container. They seed local Users, Subscriptions and usage without calling providers. The usage smoke tests need the dummy billing configuration and caps in [CONTRIBUTING.md](../../CONTRIBUTING.md#make-targets); they stub the Stripe-backed catalog response and cancel purchase dialogs before payment.

## Browsers

Chrome, Firefox, Edge, `curl` and Node's `fetch` resolve `*.localhost` on their own. Safari may not: run `portless hosts sync` once when a Dev URL doesn't resolve there.
