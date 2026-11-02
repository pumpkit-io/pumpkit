# Releasing

For maintainers. A release is a tag `vX.Y.Z` on `main`. Pushing it runs `.github/workflows/release.yml`, which checks the tag against `.env.example` and `CHANGELOG.md`, builds `ghcr.io/pumpkit-io/pumpkit-backend` and `ghcr.io/pumpkit-io/pumpkit-web` for linux/amd64 and linux/arm64, each platform on its own native runner, pushes them as `X.Y.Z` and `latest`, and creates a GitHub Release whose notes are the version's CHANGELOG section.

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
4. Turns on auto-merge with `gh pr merge --auto --squash --delete-branch` as soon as the PR is open, on every run, so GitHub merges the PR once every required check passes, `review` included, even if the script has stopped by then. It never turns auto-merge off. Then it dispatches `sdlc-review-llm.yml` on the branch, so the review runs alongside CI, unless the head commit already has a final `review` status or a review run going. When `gh` fails to read either, it starts nothing and tries again on the next poll, so a network blip never starts a second review.
5. Waits up to an hour for GitHub to merge the PR, stopping early on a failed check or review. It reads the PR's head commit on every poll, and when a push moves it, starts the review on the new commit and judges that commit's review from then on. Once merged, it reads the Release PR's merge commit from GitHub and runs `scripts/tag-release.sh X.Y.Z <merge commit>`, so a PR merged to main after the Release PR stays out of the tag. That tags the merge commit (refusing unless it is on `origin/main`, `.env.example` and the CHANGELOG name X.Y.Z there, and the tag is new), pushes only the tag, and watches the Release workflow. If the watch drops its connection it retries, and it reports a failure only when the run's conclusion is `failure` or `cancelled`; if the conclusion stays unknown it prints the run URL instead.
6. Reads both image manifests from `ghcr.io`, checks for `linux/amd64` and `linux/arm64`, removes the worktree and prints `Released vX.Y.Z`.

Each stop prints a `STOPPED:` line saying what is wrong and a `NEXT:` line saying what to do; fix that and run the command again. Once the Release PR is open, run it again with the same version, `sh scripts/release.sh X.Y.Z`: run without one, it chooses the version again from main's `## [Unreleased]`, which may have changed, and could open a second Release PR. It picks up where it stopped: it reuses the worktree, the branch and an open PR, fast-forwards the worktree to any fix pushed to the release branch from another checkout, and when the latest release in the CHANGELOG is merged but untagged it goes straight to the tag.

`sh scripts/release-notes.sh --manual-steps X.Y.Z` (or `FROM..TO`) prints only the entries with Upgrade notes, and nothing when there are none; the deploy reads it.

The stops, and what to do:

- **Merged PRs without an entry:** add each entry under `## [Unreleased]`, saying what changed for Users or Self-hosters, in a PR, or label the PR `no-changelog`. Where a change needs a manual step on upgrade (a new required setting in `.env.example`, a changed compose file, a destructive migration), add an **Upgrade notes:** line saying what to do. An entry with nothing to do by hand says so in its prose and carries none.
- **Nothing to release:** `## [Unreleased]` has no entries. Stop there.
- **Uncommitted changes in the release worktree:** commit or discard them in `.claude/worktrees/release-vX.Y.Z`, and run the command again.
- **The release worktree can't fast-forward:** it and the release branch on origin each have commits the other doesn't. Rebase the worktree onto `origin/release/vX.Y.Z`, or drop its own commits with `git reset --hard origin/release/vX.Y.Z` there, and run the command again.
- **gh could not turn on auto-merge:** run `gh pr merge <PR> --auto --squash --delete-branch` yourself, and run the command again.
- **Not an admin:** only a repository admin can run the review. The script has turned on auto-merge, so ask a maintainer to run `gh workflow run sdlc-review-llm.yml --ref release/vX.Y.Z`; once the review passes GitHub merges the PR, and running the command again tags it.
- **gh could not start the review workflow:** run `gh workflow run sdlc-review-llm.yml --ref release/vX.Y.Z` yourself, and run the command again.
- **The review run ended without a final status:** it ended before posting one, for example cancelled or failed before finding the PR. Read it with `gh run list --workflow sdlc-review-llm.yml --branch release/vX.Y.Z`, fix the cause, and run the command again; it starts a new review.
- **A check or the review failed:** read it with `gh pr checks <PR>` or the review's comment on the PR, push a fix to the release branch and run the command again, which starts the review on the new commit. Auto-merge stays on, and the new commit can't merge before its own review passes.
- **The review ended `error`:** the review run was cancelled or timed out, and that leaves no new comment on the Release PR (an older one there may be about an earlier commit). Read the run with `gh run list --workflow sdlc-review-llm.yml --branch release/vX.Y.Z`, and start it again with `gh workflow run sdlc-review-llm.yml --ref release/vX.Y.Z`. Auto-merge is still on, so GitHub merges the PR once it passes, and running the command again tags it.
- **The Release PR conflicts with main:** a PR merged to main during the wait, usually touching `CHANGELOG.md`, so the Release PR's checks don't run and GitHub can't merge it. Bring the release worktree up to date with the release branch and merge main into it with `git -C .claude/worktrees/release-vX.Y.Z fetch origin && git -C .claude/worktrees/release-vX.Y.Z merge --ff-only origin/release/vX.Y.Z && git -C .claude/worktrees/release-vX.Y.Z merge origin/main`, and resolve the conflicts. In `CHANGELOG.md`, move each entry that arrived under `## [Unreleased]` into `## [X.Y.Z]`, since its code ships in this Release. Push, and run the command again. Auto-merge stays on.
- **Not merged after an hour:** a check or the review is still pending. Auto-merge is still on, so GitHub merges the PR when they pass; see where they stand with `gh pr checks <PR>`, and run the command again later to tag it.

## When the Release workflow fails

Read the failure with `gh run view <run id> --log-failed`.

- **The `check` job failed:** nothing was published. Delete the tag (`git push origin :refs/tags/vX.Y.Z && git tag -d vX.Y.Z`), fix the cause in a PR, merge it, and run `sh scripts/release.sh` again, which tags the merged release.
- **An `images`, `manifests` or `release` job failed** (a flaky build or registry): rerun it with `gh run rerun <run id> --failed`. Re-tag only if the cause needs a code change, and then release the next patch version instead: images already pushed under X.Y.Z must not change.

## Trying the Release workflow

To check that both images still build after a Dockerfile change, run the workflow by hand on your branch: `gh workflow run release.yml --ref <branch>`. It builds all four images, backend and web for each platform, and pushes and releases nothing.

To try the Release workflow before the real tag, tag a pre-release once the release PR is merged: `sh scripts/tag-release.sh X.Y.Z-rc.1`. The workflow checks `.env.example` against `X.Y.Z`, so it only passes once the release PR is merged. A pre-release pushes only `:X.Y.Z-rc.1` (no `latest`) and creates a GitHub pre-release, which pumpkit.io never deploys. Remove it afterwards with `gh release delete vX.Y.Z-rc.1 --cleanup-tag`, and delete the rc package versions in GHCR if you don't want them, then tag the real release.

On a fork, change `ghcr.io/pumpkit-io/` in the workflow's matrix to the fork's owner, or the push is denied.

## After a release

A release changes no running Instance: each Operator upgrades their own ([self-hosting.md](self-hosting.md#upgrades)). pumpkit.io's Operator keeps its deploy steps in a private repo.
