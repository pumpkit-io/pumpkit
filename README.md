# Pumpkit

Open-source AI writing tool for X: turns a brief into a post written in the style of X authors you choose, then revises it with your feedback.

> **Status:** early development. Not ready for production use yet.

Website: https://pumpkit.io

## Getting started

You need Docker with Compose. For running tests and tooling outside Docker, also Node.js 22+ and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env && cp backend/.env.example backend/.env && cp frontend/.env.example frontend/.env
# Generate secrets
python3 -c "import secrets; print(secrets.token_urlsafe(48))"          # JWT_SECRET_KEY, POSTGRES_PASSWORD
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # FERNET_ENCRYPTION_KEY
docker compose up --build
```

Fill in the remaining values in the three `.env` files (Resend, which sends Magic links; Stripe; optionally Google). Every variable is described in [docs/configuration.md](./docs/configuration.md). Users sign in only with Google or a Magic link (see [ADR 0002](./docs/adr/0002-google-and-magic-link-only.md)). Then open the app at http://localhost:5173 and the API docs at http://localhost:8000/docs.

To receive Stripe webhooks locally:

```bash
stripe listen --forward-to localhost:8000/api/v1/stripe/webhook
```

Use the `whsec_...` secret it prints as `STRIPE_WEBHOOK_SECRET`.

More: [project layout and recipes](./docs/development.md), [deployment](./docs/deployment.md).

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md). Security issues: [SECURITY.md](./SECURITY.md).

## License

GNU Affero General Public License v3.0, copyright Francesco Paoli Leonardi (@prafaolo on X). See [LICENSE](./LICENSE).
