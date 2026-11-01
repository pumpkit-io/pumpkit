<h1 align="center">
  <img src="docs/assets/pumpkit-mascot.gif" alt="" height="100">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/pumpkit-wordmark-dark.svg">
    <img src="docs/assets/pumpkit-wordmark-light.svg" alt="Pumpkit" height="100">
  </picture>
</h1>

An open-source AI writing tool for X.

- Write a Brief: what the post is about and what you think about it.
- Pick up to three X authors whose style you like. Pumpkit writes the post the way they would.
- Give Feedback in plain words, such as "shorter" or "drop the last line", and get a new Version each time.
- Schedule the result on your X account, or post it now.

Use the hosted Instance at [pumpkit.io](https://pumpkit.io), or run your own from this repository.

> [!NOTE]
> Pumpkit is pre-1.0. Upgrades may need manual steps, listed in the [CHANGELOG](./CHANGELOG.md).

## Self-host

You need Docker with Compose v2, git and openssl, plus two API keys:

- an **LLM key**, for [OpenRouter](https://openrouter.ai/settings/keys) or any other OpenAI-compatible endpoint;
- a **[twitterapi.io](https://twitterapi.io/dashboard) key**, to read the posts of the authors you pick.

The full guide, covering servers, HTTPS, every provider, backups, upgrades and troubleshooting, is [docs/self-hosting.md](./docs/self-hosting.md).

### With an AI agent

Paste this into Claude Code or another coding agent, in an empty folder:

```
Self-host Pumpkit for me from https://github.com/pumpkit-io/pumpkit.
Clone it, check out the latest release tag, then follow docs/self-hosting.md,
starting with its "For agents" section. Ask me before changing anything,
and never print my keys or commit .env.
```

> [!IMPORTANT]
> **AI agents reading this file:** to self-host Pumpkit, clone this repository, run `git checkout "$(git describe --tags --abbrev=0)"`, then open `docs/self-hosting.md` and follow its **For agents** section. That guide is the source of truth: run each step's **Check** before moving on, and ask the user for keys one provider at a time. Pass keys to `scripts/setup.sh` as environment variables, never print them, and never commit `.env`.

### By hand, on your computer

```sh
git clone https://github.com/pumpkit-io/pumpkit.git
cd pumpkit
git checkout "$(git describe --tags --abbrev=0)"   # the latest release

# Writes .env and generates every secret
LLM_API_KEY='<your LLM key>' TWITTERAPI_IO_API_KEY='<your twitterapi.io key>' \
  sh scripts/setup.sh --public-url http://localhost:8080 </dev/null

docker compose up -d --wait          # the first start takes a minute or two
curl -s http://localhost:8080/api/v1/health
```

The last command prints `{"status":"ok"}`.

To sign in, open http://localhost:8080, choose **Get started** and send yourself a Magic link. Until you set up SMTP, the link goes to the backend log instead of your inbox:

```sh
docker compose logs backend | grep "Magic link for"
```

Open the link in the same browser. On Home, add an X handle under **Inspiration authors**, type a Brief and choose **Write the post**.

To run Pumpkit on a server with your own domain and HTTPS, follow [the guide](./docs/self-hosting.md). [Configure SMTP](./docs/self-hosting.md#smtp) before you invite anyone else.

## Providers

Only the first two are required. Each optional provider stays off until you set its keys.

| Provider | Required | What it adds |
| --- | --- | --- |
| LLM endpoint | Yes | Writes and revises Posts |
| twitterapi.io | Yes | Reads your Inspiration authors' posts, which set the style |
| SMTP | No | Emails Magic links. Without it, links go to the backend log and only you can sign in |
| Google | No | "Continue with Google" on the sign-in page |
| X app | No | Connects X accounts to schedule Posts or post now. Without it, Users copy a Version's text into X |
| Stripe | No | Sells Plans. Without it, every User can use all of Pumpkit |
| Operator details | No | Company footer, Terms and Privacy Policy pages |
| PostHog | No | Product analytics, behind a consent banner |

The guide's [Providers](./docs/self-hosting.md#providers) section says where to get each key, links each pricing page and lists the callback URLs to register. [docs/configuration.md](./docs/configuration.md) describes every setting.

## Use Pumpkit from AI apps

Pumpkit serves an MCP server at `PUBLIC_URL/api/v1/mcp`. Paste that URL into Claude, ChatGPT, Claude Code, Codex, Gemini CLI, Cursor or VS Code, sign in to Pumpkit and click Allow: there is no key to copy. The app can then write and revise posts, manage your inspiration authors, and schedule or publish posts. Settings shows the URL and the steps for each app, and lists the apps you connected. See [docs/mcp.md](./docs/mcp.md).

Self-hosted Instances get the MCP server in the first release after 0.1.0.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the development setup. Report security issues as described in [SECURITY.md](./SECURITY.md).

## License

[GNU AGPL v3.0](./LICENSE), copyright Francesco Paoli Leonardi ([@prafaolo](https://x.com/prafaolo) on X).

---

<p align="center">
  <img src="docs/assets/pumpkit-star.gif" alt="The Pumpkit mascot waving a yellow star" height="96">
</p>

<p align="center">
  <b>Every star is a blessing for this little pumpkin.</b><br>
  If Pumpkit helps you, leave a ⭐ on the repository. It helps other people find it.
</p>
