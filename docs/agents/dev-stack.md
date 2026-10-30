# Dev stack

- Entry point: `scripts/dev-stack`
- Strategy: B
- Project: `pumpkit`
- Health URL: `/api/v1/health`
- e2e: `cd e2e && npm test`
- Cap: 4
- Portless: 0.15.12
- Proxy: HTTP on 1355

## Safe mode

- `PUBLISHER_ENABLED=false`: the publisher process runs but publishes nothing to X.
- `SMTP_HOST=`: Magic links are logged instead of emailed.
- `POSTHOG_ENABLED=false`: the backend sends no analytics events.

## Browsers

Chrome, Firefox, Edge, `curl` and Node's `fetch` resolve `*.localhost` on their own. Safari may not: run `portless hosts sync` once when a Dev URL doesn't resolve there.
