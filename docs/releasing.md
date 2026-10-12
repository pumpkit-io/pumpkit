# Releasing

For maintainers. Pushing a tag `vX.Y.Z` runs `.github/workflows/release.yml`: it checks the tag against `.env.example` and `CHANGELOG.md`, builds `ghcr.io/pumpkit-io/pumpkit-backend` and `ghcr.io/pumpkit-io/pumpkit-web` for linux/amd64 and linux/arm64, pushes them as `X.Y.Z` and `latest`, and creates a GitHub Release whose notes are the version's CHANGELOG section.

## Cut a release

1. On a branch, move the entries under `## [Unreleased]` in `CHANGELOG.md` to a new `## [X.Y.Z] - YYYY-MM-DD` heading, leaving an empty `## [Unreleased]` above it. If upgrading needs manual steps, list them under **Upgrade notes** in the new section.
2. Set `PUMPKIT_VERSION=X.Y.Z` in `.env.example`, without the `v`.
3. Run `sh scripts/release-notes.sh X.Y.Z`. **Check:** it prints the new section and exits 0. Merge the PR.
4. Tag `main` and push only the tag:

   ```sh
   git checkout main && git pull
   git tag -a vX.Y.Z -m vX.Y.Z
   git push origin vX.Y.Z
   ```

5. Watch the workflow:

   ```sh
   gh run watch $(gh run list --workflow release.yml --limit 1 --json databaseId -q '.[0].databaseId')
   ```

   **Check:** every job passes.
6. First release only: GHCR creates both packages as private. In the organisation's Packages settings, set `pumpkit-backend` and `pumpkit-web` to Public and check that each is linked to `pumpkit-io/pumpkit`, so Self-hosters pull them without logging in.
7. Check the release, on an amd64 and an arm64 machine, logged out of `ghcr.io`:

   ```sh
   docker pull ghcr.io/pumpkit-io/pumpkit-backend:X.Y.Z
   docker pull ghcr.io/pumpkit-io/pumpkit-web:X.Y.Z
   docker buildx imagetools inspect ghcr.io/pumpkit-io/pumpkit-web:X.Y.Z
   gh release view vX.Y.Z
   ```

   **Check:** both pulls succeed, `imagetools inspect` lists `linux/amd64` and `linux/arm64`, and the release shows the CHANGELOG section.

A tag with a prerelease suffix, such as `v0.1.0-rc.1`, is a dry run: it uses the Unreleased section when the CHANGELOG has none for it, pushes only `:0.1.0-rc.1` (no `latest`) and creates a GitHub pre-release. Remove it afterwards with `gh release delete v0.1.0-rc.1 --cleanup-tag`, and delete the rc package versions in GHCR if you don't want them. On a fork, change `ghcr.io/pumpkit-io/` in the workflow's matrix to the fork's owner, or the push is denied.

## Deploy pumpkit.io

The Operator runs the hosted Instance the way a Self-hoster runs theirs: the server path of [self-hosting.md](self-hosting.md), with the same compose file and release images. Its `.env` also sets:

- the [external Postgres](self-hosting.md#external-postgres) settings for the managed database, with `COMPOSE_FILE=compose.yml:compose.external-db.yml` and `POSTGRES_SSL=require`;
- `POSTHOG_RELAY=true` and `POSTHOG_HOST=https://pumpkit.io/ph-relay`, with the PostHog keys;
- `ALLOW_SEARCH_INDEXING=true`;
- the Operator details and `SUPPORT_EMAIL`, and the Stripe billing group.

Each deploy is [an upgrade](self-hosting.md#upgrades): read the CHANGELOG, set `PUMPKIT_VERSION`, pull, `docker compose up -d --wait`, then check `https://pumpkit.io/api/v1/health` prints `{"status":"ok"}`.
