---
status: accepted
---

# Local Compose is for personal testing; agent stacks use emulators

Use `docker compose -f compose.dev.yml up --build` for personal testing at `http://localhost:5173`, with persistent local data and the real providers configured in the root `.env`. Neither `DEV_PUBLIC_URL` nor `DEV_PUBLIC_PORT` is required. Agent stacks remain an explicit override, started through `scripts/dev-stack` in their own worktrees, with generated URLs, separate Compose projects and volumes, and fake credentials for the emulated providers. Keeping personal testing in the base configuration preserves the existing command and data instead of requiring another startup mode.

## Personal testing

The development configuration enables the existing X callback relay in the backend and frontend. Register `http://127.0.0.1:5173/oauth/x/callback` with X; the browser returns through that address and the relay redirects to localhost before the frontend completes sign-in. Keep state, PKCE, browser binding, callback credential handling and the production restriction unchanged. Defaults agree across services without additional environment variables. Local frontend access binds to IPv4 and IPv6 loopback.

Scheduled publishing follows `PUBLISHER_ENABLED`, retaining the current default of enabled. Manual publishing and media requests use real X. Other providers follow their existing configuration and consent rules. When billing is configured, personal development accepts Stripe sandbox credentials and rejects live credentials. An Instance without billing configuration continues to sell no Plans, as ADR 0011 requires. This development-only constraint does not change production or Self-hosters' production configuration.

Preserve the `pumpkit-dev` Compose project and existing Postgres and media volume names. Rebuilding or restarting must retain personal data and identity keys. Mark the personal frontend so E2E refuses it before seeding or browser activity, even when the stack was started directly through Compose.

## Agent testing

The emulator override explicitly disables the callback relay wherever inherited, including the staged X fixture, and supplies the correct frontend environment for generated URLs. Keep per-worktree project and volume isolation, throwaway provider credentials, and the existing disabled scheduled publisher, mail and analytics. Agent startup must not attach to or reconfigure the personal stack.

This change preserves the current emulator coverage: X and Stripe are emulated; the retained inactive Google adapter has a test provider. Writing, twitterapi.io and the classifier may still call their configured real services. Extending emulator coverage is separate work.

## Remove redundant modes

Remove `compose.personal.yml`, `compose.real-x.yml` and the script's `--personal` and `--real-x` startup modes. Personal real-provider testing has one supported path; agents have the emulated path. Remove obsolete mode-specific tests and configuration, retaining checks that enforce the two supported paths. Calls using removed flags must fail with an explanation of the replacement rather than silently start an emulated stack.

Existing volumes belonging to retired modes are left untouched. Do not copy, migrate, reset or delete their data automatically. Document how to identify and recover old data explicitly. Likewise, stale mode state must produce an actionable diagnostic rather than select a different project or destroy volumes.

## Considered options

- Keeping a separate personal override preserves redundant startup choices and leaves the familiar Compose command unsuitable for localhost X sign-in.
- Moving personal testing to the agent launcher changes the requested workflow and selects a different database project.
- Sharing projects or volumes between personal and agent stacks lets automated fixtures affect personal data.

## Implementation inputs

Update the Compose files, development startup and validation paths, frontend relay wiring, affected tests, Make targets and development documentation together. The repo's agent instructions currently require all stack operations to use `scripts/dev-stack`; clarify that this remains mandatory for agents while humans may use plain Compose for personal testing. Add the required changelog entry. Verify default URLs with both `DEV_*` variables absent, sandbox-only billing when configured, persistent personal volumes, generated agent origins, fake provider credentials, and E2E refusal of the personal target. Real X sign-in still needs a human check against the registered callback; emulated tests cannot prove provider acceptance.
