# Pumpkit

Pumpkit is an open-source AI writing tool for X. You write a Brief saying what a post is about and what you think, pick up to three X authors whose style you like, and Pumpkit writes the post in their style, then revises it with your Feedback. It can also schedule the result on your X account. The hosted Instance is at https://pumpkit.io; this repository runs your own.

**Status:** pre-1.0: upgrades may need manual steps, read the [CHANGELOG](./CHANGELOG.md).

## Self-host with an AI agent

Open a Claude Code chat on your laptop, in an empty folder or in a clone of this repository, and paste:

```
I want to self-host Pumpkit (https://github.com/pumpkit-io/pumpkit), an open-source AI writing tool for X.

1. Clone the repository into a new folder, or use this folder if it is already a clone.
2. Read docs/self-hosting.md and follow it. It is the source of truth for every step.
3. Before changing anything, ask me whether to run Pumpkit on this computer or on a server I can reach over SSH. For a server, ask for the SSH host and the domain name.
4. Ask me for each provider key one at a time. For each, tell me where to get it, what it costs, and what stops working if I skip it. Skip the optional providers I don't want.
5. Never print my secrets or keys back to me, and never commit the .env file.
6. After each step, run the check the guide gives. If a check fails, stop and tell me what went wrong.
7. When you finish, run the health check, then tell me the URL to open and how to sign in.
```

## Self-host by hand

These steps run Pumpkit on your computer at http://localhost:8080. For a server with a domain and HTTPS, and for every optional provider, follow [docs/self-hosting.md](./docs/self-hosting.md). You need Docker with Compose v2, git, an LLM API key and a twitterapi.io API key (see [Providers](#providers)).

1. Check Docker Compose:

   ```sh
   docker compose version
   ```

   Check: it prints `Docker Compose version v2.` and the rest of the version.

2. Get the code:

   ```sh
   git clone https://github.com/pumpkit-io/pumpkit.git
   cd pumpkit
   ls compose.yml .env.example
   ```

   Check: `ls` prints `.env.example` and `compose.yml`.

3. Write `.env`, with the secrets generated for you:

   ```sh
   LLM_API_KEY='<your LLM key>' TWITTERAPI_IO_API_KEY='<your twitterapi.io key>' \
     sh scripts/setup.sh --public-url http://localhost:8080 </dev/null
   ```

   Check: it prints `Wrote /path/to/pumpkit/.env (mode 600).`, then `Generated: POSTGRES_PASSWORD JWT_SECRET_KEY FERNET_ENCRYPTION_KEY` and `Set: PUBLIC_URL LLM_API_KEY TWITTERAPI_IO_API_KEY`. Run `sh scripts/setup.sh` with no arguments instead and it asks for each value.

4. Start Pumpkit:

   ```sh
   docker compose up -d --wait
   ```

   Check: it exits once every service is healthy, and `docker compose ps --format 'table {{.Service}}\t{{.Status}}'` lists `backend`, `db`, `publisher` and `web`, each `Up` and `(healthy)`.

5. Check its health:

   ```sh
   curl -s http://localhost:8080/api/v1/health
   ```

   Check: it prints `{"status":"ok"}`.

6. Sign in. Open http://localhost:8080, choose **Get started**, enter your email address and send the Magic link. Without SMTP, the link goes to the backend log:

   ```sh
   docker compose logs backend | grep "Magic link for"
   ```

   Check: it prints `... [WARNING] Magic link for you@example.com (expires in 15 minutes): http://localhost:8080/api/v1/login/magic-link?token=...`. Open that URL in the same browser; it lands on Home, with your address in the sidebar.

7. Write a Post: add an X handle under **Inspiration authors**, type a Brief and choose **Write the Post**. Check: after a minute or two, a Version appears with its Final and Draft.

Before you invite anyone else, configure SMTP so Magic links arrive by email ([SMTP](./docs/self-hosting.md#smtp)). To upgrade, read the CHANGELOG, then follow [Upgrades](./docs/self-hosting.md#upgrades).

## Providers

| Provider | Required | What it enables | Without it |
| --- | --- | --- | --- |
| LLM endpoint (OpenRouter or any OpenAI-compatible endpoint) | Yes | Writing and revising Posts | `scripts/setup.sh` stops and asks for `LLM_API_KEY` |
| twitterapi.io | Yes | Reading Inspiration authors' posts, which set the writing style | `scripts/setup.sh` stops and asks for `TWITTERAPI_IO_API_KEY` |
| SMTP | No | Emailing Magic links | Magic links go to the backend log, so only you can sign in |
| Google | No | Signing in with Google | Users sign in with a Magic link only |
| X app | No | Connecting an X account to schedule Posts or post them now | Users copy the Final into X themselves |
| Stripe | No | Selling Plans | No Plans are sold; every User may use all of Pumpkit |
| Operator details | No | The company footer, Terms and Privacy Policy pages, and Terms at checkout | Those are hidden |
| PostHog | No | Product analytics behind a consent banner | No analytics and no banner |

[docs/self-hosting.md](./docs/self-hosting.md#providers) says where to get each key, links each pricing page, and lists the callback URLs to register. [docs/configuration.md](./docs/configuration.md) describes every setting.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the development setup. Security issues: [SECURITY.md](./SECURITY.md).

## License

GNU Affero General Public License v3.0, copyright Francesco Paoli Leonardi (@prafaolo on X). See [LICENSE](./LICENSE).
