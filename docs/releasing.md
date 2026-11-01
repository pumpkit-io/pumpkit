# Releasing

For maintainers. A release is a tag `vX.Y.Z` on `main`. Pushing it runs `.github/workflows/release.yml`, which checks the tag against `.env.example` and `CHANGELOG.md`, builds `ghcr.io/pumpkit-io/pumpkit-backend` and `ghcr.io/pumpkit-io/pumpkit-web` for linux/amd64 and linux/arm64, pushes them as `X.Y.Z` and `latest`, and creates a GitHub Release whose notes are the version's CHANGELOG section.

The CHANGELOG is written as the work lands: every PR adds its entry under `## [Unreleased]`, or carries the `no-changelog` label, and the Changelog workflow fails the PR otherwise. Cutting a release only moves those entries under a version.

## Cut a release

```sh
sh scripts/release.sh --dry-run   # prints the version and the PRs it would cover, changes nothing
sh scripts/release.sh             # cuts the release
sh scripts/release.sh X.Y.Z       # the same with a version you choose
```

Run it from any checkout or worktree; it needs `gh` logged in as a repository admin and Docker. It works in a `release/vX.Y.Z` worktree off `origin/main` under `.claude/worktrees/`, and goes through these steps:

1. Lists the PRs merged since the last release and stops on any without a CHANGELOG entry or the `no-changelog` label.
2. Chooses the version from the Unreleased entries, unless you give one. Before 1.0, any `### Added`, `### Changed`, `### Removed` or **Upgrade notes** means the next minor (`0.2.3` becomes `0.3.0`), and only `### Fixed` or `### Security` means the next patch (`0.2.3` becomes `0.2.4`).
3. Runs `scripts/prepare-release.sh`, which moves the Unreleased entries under `## [X.Y.Z] - <today>`, leaves an empty `## [Unreleased]` above and sets `PUMPKIT_VERSION=X.Y.Z` in `.env.example`. Then it commits `Release X.Y.Z`, pushes the branch and opens the PR with the release notes as its summary.
4. Waits for the PR's checks, dispatches `sdlc-review-llm.yml` on the branch and waits for the `review` status.
5. Merges the PR with `gh pr merge --squash --delete-branch`, then runs `scripts/tag-release.sh`. That tags the tip of `origin/main` (refusing unless `.env.example` and the CHANGELOG name X.Y.Z there and the tag is new), pushes only the tag, and watches the Release workflow. If the watch drops its connection it retries, and it reports a failure only when the run's conclusion is `failure` or `cancelled`; if the conclusion stays unknown it prints the run URL instead.
6. Reads both image manifests from `ghcr.io`, checks for `linux/amd64` and `linux/arm64`, removes the worktree and prints `Released vX.Y.Z`.

Each stop prints a `STOPPED:` line saying what is wrong and a `NEXT:` line saying what to do; fix that and run the command again. It picks up where it stopped: it reuses the worktree, the branch and an open PR, and when the latest release in the CHANGELOG is merged but untagged it goes straight to the tag.

`sh scripts/release-notes.sh --manual-steps X.Y.Z` (or `FROM..TO`) prints only the entries with Upgrade notes, and nothing when there are none; the deploy reads it.

The stops, and what to do:

- **Merged PRs without an entry:** add each entry under `## [Unreleased]`, saying what changed for Users or Self-hosters, in a PR, or label the PR `no-changelog`. Where a change needs a manual step on upgrade (a new required setting in `.env.example`, a changed compose file, a destructive migration), add an **Upgrade notes:** line saying what to do. An entry with nothing to do by hand says so in its prose and carries none.
- **Nothing to release:** `## [Unreleased]` has no entries. Stop there.
- **Not an admin:** only a repository admin can run the review. Ask a maintainer to run `gh workflow run sdlc-review-llm.yml --ref release/vX.Y.Z`, then run the command again.
- **A check or the review failed:** read it with `gh pr checks <PR>` or the review's comment on the PR, push a fix to the release branch (a new commit needs a new review run) and run the command again.
- **The merge was refused:** `gh pr view <PR>` says why, usually a required check still pending.

## When the Release workflow fails

Read the failure with `gh run view <run id> --log-failed`.

- **The `check` job failed:** nothing was published. Delete the tag (`git push origin :refs/tags/vX.Y.Z && git tag -d vX.Y.Z`), fix the cause in a PR, merge it, and run `sh scripts/release.sh` again, which tags the merged release.
- **The `images` or `release` job failed** (a flaky build or registry): rerun it with `gh run rerun <run id> --failed`. Re-tag only if the cause needs a code change, and then release the next patch version instead: images already pushed under X.Y.Z must not change.

## Trying the Release workflow

To try the Release workflow before the real tag, tag a pre-release once the release PR is merged: `sh scripts/tag-release.sh X.Y.Z-rc.1`. The workflow checks `.env.example` against `X.Y.Z`, so it only passes once the release PR is merged. A pre-release pushes only `:X.Y.Z-rc.1` (no `latest`) and creates a GitHub pre-release, which pumpkit.io never deploys. Remove it afterwards with `gh release delete vX.Y.Z-rc.1 --cleanup-tag`, and delete the rc package versions in GHCR if you don't want them, then tag the real release.

On a fork, change `ghcr.io/pumpkit-io/` in the workflow's matrix to the fork's owner, or the push is denied.

## After a release

A release changes no running Instance: each Operator upgrades their own ([self-hosting.md](self-hosting.md#upgrades)). pumpkit.io's Operator keeps its deploy steps in a private repo.
