# Changelog

Every release of Pumpkit gets a section here, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/).

Before 1.0, upgrades may need manual steps. Read the section for every version between yours and the one you are upgrading to, and follow any steps listed under **Upgrade notes**.

## [Unreleased]

### Added

- History on the Post's page: a clock in the dock lists every Version, newest first, with its Brief or Feedback and when it was written, and clicking one makes it the Text again. It opens as a bottom sheet on a phone. The `restore_version` MCP tool does the same for agents, and `POST /api/v1/posts/{id}/versions/{number}/restore` for the API.
- Editing the Text in place on a Draft or a Failed Post. Each Part's text is editable where it stands, the number and order of Parts stay, and Parts already live on a Failed Thread stay locked. Edits save on their own a moment after you stop typing, and a failed save says "Edit not saved. Retrying." and tries again; "Post to…" waits until the edit is saved. The API saves the Text with `PUT /api/v1/posts/{id}/text`. A Part left blank can't be scheduled.
- Undo and redo on the Post's page, in the dock and with ⌘Z and ⇧⌘Z (Ctrl+Z and Ctrl+Shift+Z) while editing. They step through every change to the Text in this tab: each burst of typing, each rewrite from Feedback and each restore from History, and the origin line follows. The words that changed are briefly highlighted, and screen readers hear what was undone or redone. Typing after an undo drops what redo would have reached; rewrites dropped that way stay in History. A reload starts a fresh undo line.
- Inspiration authors' X photos on the Persona page, left of each handle, with their initial when there is none or it fails to load. Pumpkit stores X's link to the photo, not a copy, each time it fetches an author's posts, and `GET /api/v1/inspiration-authors` returns it as `photo_url`; the MCP tools answer as before. **Upgrade notes:** the backend applies a database migration when it starts that makes room for the photo; there is nothing to do by hand.
- A one-off backfill that gives Inspiration authors listed before this release their X photo, so Users don't have to refresh each one. **Upgrade notes:** once the upgraded backend is running, run `docker compose exec backend python -m pumpkit.authors.photo_backfill` once. It makes one twitterapi.io request per listed handle without a photo, logs and skips any that fail, and ends by reporting how many it filled and skipped; running it again only retries the skipped ones.
- Signing in with Google gives you your Google account's picture as your Photo, copied to the server, if you have no Photo and have never saved or removed one in Settings. A picture that fails to download never blocks sign-in, and the next sign-in tries again. **Upgrade notes:** the backend applies a database migration when it starts that marks every existing Photo as chosen, so none is replaced; there is nothing to do by hand.
- The X account's photo, beside its handle in Settings and in the Post's preview, with initials while it loads or when X has none. Pumpkit reads it from X when you connect and again whenever it refreshes the connection's tokens. `GET /api/v1/x-connection` returns it as `photo_url`. **Upgrade notes:** the backend applies a database migration when it starts; an X connection made before it shows its photo after its next token refresh or reconnect, with nothing to do by hand.

### Changed

- The sidebar shows Persona as a plain link, without the "N/3" count of Inspiration authors.
- New post is a composer: one line, a box to ramble in with the Format toggle inside it, and a send arrow. ⌘Enter (Ctrl+Enter) writes the Post, and Enter adds a newline.
- The Post's page shows the Text as the X post it will become, with a copy icon at its corner, above a dock pinned to the bottom: one line saying which Version and which Brief or Feedback the Text came from, which opens in full, then Feedback in a composer with "Post to…", or the Scheduled or Published status. The version pager, the Brief block and the machine-written tells are gone, and copying a Thread puts a line of `---` between its Parts.
- A Post has one Text, the text meant for X, set from each new Version. `GET /api/v1/posts/{id}` and the `get_post` MCP tool return it with the number of the Version it came from and whether it was edited since, and every Version now carries its creation time. **Upgrade notes:** the backend applies a database migration when it starts that sets every existing Post's Text from its latest Version; there is nothing to do by hand.
- A Scheduled post is copied from its Post's Text, not from a Version. "Post to…" and the retry on a Failed Post send the Text, and a Failed Thread keeps its live Parts first. `POST /api/v1/scheduled-posts` and the `schedule_post` and `post_now` MCP tools take `post_id` instead of a Version id; `PATCH /api/v1/scheduled-posts/{id}` and `edit_scheduled_post` take `copy_text` to copy the Text again in place of a Version id. Scheduled posts no longer return `source_version_id`. **Upgrade notes:** agents or scripts that pass a Version id to `schedule_post`, `post_now` or `edit_scheduled_post` must pass the Post's id (or `copy_text`) instead; the old argument is refused. The backend applies a database migration when it starts that drops each Scheduled post's link to its Version and keeps every Scheduled post; there is nothing to do by hand.
- Feedback rewrites the Post's Text as it is, your edits and a restored Version included, in the web app and through the `give_feedback` MCP tool. The writing sees every Version in order with what you did before each Feedback, the humanizer sees every Feedback you gave and keeps the sentences you wrote by hand, and each Version keeps the Text its Feedback was given on as its Starting text, returned by `GET /api/v1/posts/{id}` and `get_post`. `POST /api/v1/posts/{id}/versions` takes an optional `text`, the Parts on screen, and refuses Feedback while they aren't saved. While a Version is being written, the Post's Text takes no edit, restore or other Feedback, from an agent or another tab, so the new Version never overwrites them. **Upgrade notes:** the backend applies database migrations when it starts that give Versions room for a Starting text and Posts a record of when their next Version started being written; there is nothing to do by hand.

### Removed

- The check for machine-written tells on each new Version's text. Versions returned by `POST /api/v1/posts`, `GET /api/v1/posts/{id}` and `POST /api/v1/posts/{id}/versions` no longer carry `tells`. **Upgrade notes:** the backend applies a database migration when it starts that drops the stored tells; there is nothing to do by hand.

## [0.2.0] - 2026-10-29

### Added

- Threads. A Version can be a Thread, an ordered list of Parts that X publishes with each Part replying to the one before. A Post starts as a single X post unless the User asks for a Thread, and Feedback can switch the Format. A Scheduled post copied from a Thread keeps every Part.
- X Communities. A Scheduled post can go to an X Community instead of the User's profile, and can also be shared with their followers.
- A remote MCP server at `POST /api/v1/mcp`, so Claude Code or any MCP client can start Posts, give Feedback, manage Inspiration authors, schedule posts and Post now. Users create API keys in Settings; `docs/claude-code.md` is the guide.
- A redesigned app: New post, the Posts tabs (Scheduled, Drafts, Published, Failed), a page for each Post with its Versions, Persona for Inspiration authors, and Settings.

### Changed

- A Post goes out at most once: it has at most one Scheduled post, always copied from one of its Versions, and takes its status from it. A Scheduled post can no longer be typed by hand. **Upgrade notes:** the database migrations delete every Scheduled post that wasn't copied from a Version and, where several were copied from the same Post, all but the newest. Publish or copy any you want to keep before upgrading.
- The monthly cap counts X posts, so each Part of a Thread counts as one. **Upgrade notes:** if `.env` sets `SCHEDULED_POSTS_MONTHLY_CAP`, rename it to `X_POSTS_MONTHLY_CAP`; the old name is ignored.
- Writing a Version: the sketch and revision calls write the Hook themselves, and after Feedback the humanizer keeps the sentences the Feedback left alone. **Upgrade notes:** if `.env` sets `LLM_DRAFTING_MODEL`, rename it to `LLM_SKETCHING_MODEL`, and remove `LLM_HOOKING_MODEL`; the old names are ignored.
- A refusal from the API or an MCP tool links to the web app page that fixes it.
- The Terms and the Privacy Policy describe the redesigned app.
- The Magic link email shows the Pumpkit mascot and wordmark.
- `robots.txt` also keeps search engines out of the redesigned signed-in pages.
- Install and upgrade from the latest release tag instead of `main`, so the compose file, `setup.sh` and the docs match the release images. **Upgrade notes:** upgrade with `git fetch --tags && git checkout vX.Y.Z` instead of `git pull` (see Upgrades in `docs/self-hosting.md`).

## [0.1.0] - 2026-10-12

The first release that a Self-hoster can install.

### Added

- Prebuilt images for every release, for amd64 and arm64: `ghcr.io/pumpkit-io/pumpkit-backend` (backend and publisher) and `ghcr.io/pumpkit-io/pumpkit-web` (the built frontend served by Caddy, with automatic HTTPS). Pin a release with `PUMPKIT_VERSION` in `.env`.
- A production Docker Compose file at the repo root that runs a whole Instance: Postgres, backend, publisher and web. The backend applies database migrations when it starts, and the publisher starts once the backend is healthy. `compose.external-db.yml` swaps the bundled Postgres for an external one.
- `scripts/setup.sh`, which writes `.env` with every secret generated, keeps values already there, never prints a secret, and names each missing required value when run without a terminal.
- `GET /api/v1/health`, which answers 200 when the backend can reach the database and 503 when it cannot.
- `GET /api/v1/instance`, which tells the frontend the app name, sign-in methods, whether the Instance sells Plans, the Operator details and the analytics settings.
- Optional providers. Stripe billing, SMTP email, Google sign-in, Operator details and PostHog analytics each turn on when their settings are set and off when none are; a partly configured provider stops the backend at startup and names the missing settings. Without Stripe, every signed-in User has full access; without SMTP, Magic links go to the backend log; without Google, sign-in offers only Magic links; without Operator details, the legal pages and company footer are hidden.
- A Sign-up allowlist (`SIGN_UP_ALLOWLIST`) of addresses and `@domain` entries that may sign in.
- Any OpenAI-compatible LLM endpoint (`LLM_BASE_URL`, `LLM_API_KEY`), with the drafting, humanizing and revising models as settings.
- `POSTGRES_SSL` to require SSL on the database connection, independent of `ENV`.
- `ALLOW_SEARCH_INDEXING`, off by default, so an Instance is hidden from search engines unless it opts in.
- `docs/self-hosting.md`, the guide to running an Instance on a laptop or a server, which the README's prompt asks an AI agent to follow.
- A root `Makefile` with `dev`, `check`, `test`, `fmt`, `e2e` and `smoke`, which CI also runs.

### Changed

- One root `.env` holds every setting; `PUBLIC_URL` derives the frontend and API URLs, CORS origins, Magic link base, OAuth redirect URIs and Stripe return URLs.
- The frontend calls the API on its own origin, so `VITE_API_URL` and the other build-time `VITE_*` settings are gone.
- Email is sent over SMTP (`SMTP_*`, `EMAIL_FROM`) instead of Resend; the support address is `SUPPORT_EMAIL`.
- `OPENROUTER_API_KEY` is now `LLM_API_KEY`.
- The development stack moved to `compose.dev.yml` (`make dev`) and runs the frontend on Node 22, as CI does.
- An empty Scheduled posts cap means no cap; 0 still turns scheduling off.

### Removed

- `backend/.env.example` and `frontend/.env.example`.
- The systemd deploy: the publisher's systemd unit, `infra/Caddyfile`, `scripts/deploy.sh` with its `deploy.env.example` and PostHog deploy annotations, and `docs/deployment.md`. Deploy with the production compose file instead, following `docs/self-hosting.md`.
