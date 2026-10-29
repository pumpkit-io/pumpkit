# Releasing

For maintainers. A release is a tag `vX.Y.Z` on `main`. Pushing it runs `.github/workflows/release.yml`, which checks the tag against `.env.example` and `CHANGELOG.md`, builds `ghcr.io/pumpkit-io/pumpkit-backend` and `ghcr.io/pumpkit-io/pumpkit-web` for linux/amd64 and linux/arm64, pushes them as `X.Y.Z` and `latest`, and creates a GitHub Release whose notes are the version's CHANGELOG section.

The CHANGELOG is written as the work lands: every PR adds its entry under `## [Unreleased]`, or carries the `no-changelog` label, and the Changelog workflow fails the PR otherwise. Cutting a release only moves those entries under a version.

## Cut a release

1. Start the release branch from an up-to-date `main`. Name it after the next minor version for now (step 3 can rename it):

   ```sh
   git checkout main && git pull
   git checkout -b release/vX.Y.Z
   ```

2. Complete the Unreleased entries. List the PRs merged since the last release:

   ```sh
   gh pr list --state merged --limit 200 --json number,title,labels \
     --search "merged:>$(gh release view --json publishedAt -q .publishedAt)"
   ```

   For each PR without the `no-changelog` label, find its entry under `## [Unreleased]` in `CHANGELOG.md`; where one is missing, add it, saying what changed for Users or Self-hosters. Where a change needs a manual step on upgrade (a new required setting in `.env.example`, a changed compose file, a destructive migration), add an **Upgrade notes:** line saying what to do. Commit any additions as `Complete the CHANGELOG for X.Y.Z`.

   **Check:** every listed PR without `no-changelog` is covered by an entry, and `## [Unreleased]` has entries. If it has none, there is nothing to release: delete the branch and stop.

3. Choose the version from the Unreleased entries and the latest release (`gh release list --limit 1`). Before 1.0:

   - any `### Added`, `### Changed`, `### Removed` or **Upgrade notes** → the next minor: `0.2.3` becomes `0.3.0`;
   - only `### Fixed` or `### Security` → the next patch: `0.2.3` becomes `0.2.4`.

   If it differs from the branch name, rename the branch with `git branch -m release/vX.Y.Z`.

4. Prepare the release commit and open its PR:

   ```sh
   sh scripts/prepare-release.sh X.Y.Z
   git commit -am "Release X.Y.Z"
   git push -u origin release/vX.Y.Z
   ```

   `prepare-release.sh` moves the Unreleased entries under `## [X.Y.Z] - <today>`, leaves an empty `## [Unreleased]` above it, sets `PUMPKIT_VERSION=X.Y.Z` in `.env.example`, and prints the release notes. Open a PR titled `Release X.Y.Z` with those notes as its summary, and merge it once CI passes; the Changelog check passes on its own, because the PR adds a release section.

   **Check:** the PR changes only `CHANGELOG.md` and `.env.example`, and it is merged.

5. Tag the merge and wait for the Release workflow:

   ```sh
   git checkout main && git pull
   sh scripts/tag-release.sh X.Y.Z
   ```

   It refuses unless `main` is checked out, clean and level with `origin/main`, `.env.example` and the CHANGELOG name X.Y.Z, and the tag is new. Then it pushes only the tag, watches the workflow, and shows the release.

   **Check:** it ends by printing the GitHub Release `vX.Y.Z`. If the workflow failed, see [When the Release workflow fails](#when-the-release-workflow-fails).

6. Check the release, logged out of `ghcr.io`:

   ```sh
   docker pull ghcr.io/pumpkit-io/pumpkit-backend:X.Y.Z
   docker pull ghcr.io/pumpkit-io/pumpkit-web:X.Y.Z
   docker buildx imagetools inspect ghcr.io/pumpkit-io/pumpkit-web:X.Y.Z
   ```

   **Check:** both pulls succeed and `imagetools inspect` lists `linux/amd64` and `linux/arm64`.

## When the Release workflow fails

Read the failure with `gh run view <run id> --log-failed`.

- **The `check` job failed:** nothing was published. Delete the tag (`git push origin :refs/tags/vX.Y.Z && git tag -d vX.Y.Z`), fix the cause in a PR, merge it, and run step 5 again.
- **The `images` or `release` job failed** (a flaky build or registry): rerun it with `gh run rerun <run id> --failed`. Re-tag only if the cause needs a code change, and then release the next patch version instead: images already pushed under X.Y.Z must not change.

## Dry run

To try the Release workflow before the real tag, tag a pre-release after step 4: `sh scripts/tag-release.sh X.Y.Z-rc.1`. The workflow checks `.env.example` against `X.Y.Z`, so it only passes once the release PR is merged. A pre-release pushes only `:X.Y.Z-rc.1` (no `latest`) and creates a GitHub pre-release, which pumpkit.io never deploys. Remove it afterwards with `gh release delete vX.Y.Z-rc.1 --cleanup-tag`, and delete the rc package versions in GHCR if you don't want them, then go on with step 5.

On a fork, change `ghcr.io/pumpkit-io/` in the workflow's matrix to the fork's owner, or the push is denied.

## After a release

A release changes no running Instance: each Operator upgrades their own ([self-hosting.md](self-hosting.md#upgrades)). pumpkit.io's Operator keeps its deploy steps in a private repo.
