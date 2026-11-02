#!/bin/sh
# Cuts a release from origin/main: checks the CHANGELOG, picks the version, opens the Release PR with auto-merge, tags it once merged, checks the images.
# Usage: sh scripts/release.sh [--dry-run] [X.Y.Z], from any checkout or worktree. docs/releasing.md explains every stop.
# RELEASE_POLL_SECONDS sets the pause between polls of GitHub; the tests set it to 0.
# RELEASE_WAIT_SECONDS caps the wait for GitHub to merge the PR, an hour by default.
set -eu

scripts_dir=$(cd "$(dirname "$0")" && pwd)
poll=${RELEASE_POLL_SECONDS:-15}
wait_limit=${RELEASE_WAIT_SECONDS:-3600}
repo=pumpkit-io/pumpkit

stop() {
  printf 'STOPPED: %s\nNEXT: %s\n' "$1" "$2" >&2
  exit 1
}

step() {
  printf '\n==> %s\n' "$*"
}

review_status() {
  gh api "repos/$repo/commits/$head/statuses" -q '[.[] | select(.context == "review")][0].state // ""'
}

# The status of the newest review run on $head, or nothing when it has none.
review_run() {
  gh run list --workflow sdlc-review-llm.yml --branch "$branch" --commit "$head" --json status -q '.[0].status // ""'
}

review_run_id() {
  gh run list --workflow sdlc-review-llm.yml --branch "$branch" --commit "$head" --json databaseId -q '.[0].databaseId // ""'
}

is_final() {
  case $1 in success | failure | error) return 0 ;; esac
  return 1
}

# Returns 0 unless $head has a final review status or a review run still going, and 2 when gh could not say.
# A run that ended without a final status (cancelled, timed out, failed early) needs a new one.
review_needed() {
  needed_status=$(review_status 2>/dev/null) || return 2
  ! is_final "$needed_status" || return 1
  needed_run=$(review_run 2>/dev/null) || return 2
  case $needed_run in "" | completed) ;; *) return 1 ;; esac
}

# Dispatches the LLM review on $head unless it has one. Returns 2, having started nothing, when a gh read failed.
ensure_review() {
  if review_needed; then :; else
    [ $? -eq 1 ] || return 2
    echo "review already on $head"
    return 0
  fi
  admin=$(gh api "repos/$repo" -q .permissions.admin 2>/dev/null) || return 2
  [ "$admin" = true ] ||
    stop "your gh login is not an admin, and only an admin can run the review" "Ask a maintainer to run: gh workflow run sdlc-review-llm.yml --ref $branch. Auto-merge is on, so GitHub merges PR #$pr once it passes; then run this again to tag it."
  before=$(review_run_id 2>/dev/null) || return 2
  gh workflow run sdlc-review-llm.yml --ref "$branch" ||
    stop "gh could not start the review workflow" "Run gh workflow run sdlc-review-llm.yml --ref $branch, then run this again."
  # Until the new run is listed, the newest run on $head may be the dead one, which would read as a finished review.
  tries=0
  while [ "$tries" -lt 20 ]; do
    [ "$(review_run_id 2>/dev/null || echo "$before")" = "$before" ] || break
    sleep "$poll"
    tries=$((tries + 1))
  done
  echo "review started on $head"
}

# Tags the merged release and checks its images; also how a run resumes after a merge that was not tagged.
tag_and_check() {
  version=$1
  tag=v$version
  step "Tag"
  sh "$scripts_dir/tag-release.sh" "$version" ||
    stop "tagging $tag did not finish" "See docs/releasing.md, 'When the Release workflow fails', then run this again."

  step "Images"
  for image in pumpkit-backend pumpkit-web; do
    ref=ghcr.io/pumpkit-io/$image:$version
    manifest=$(docker buildx imagetools inspect "$ref" 2>&1) ||
      stop "could not read the manifest of $ref" "Check the Release workflow's images job with gh run list --workflow release.yml, and rerun it if it failed."
    for platform in linux/amd64 linux/arm64; do
      printf '%s\n' "$manifest" | grep -q "Platform: *$platform\$" ||
        stop "$ref has no $platform image" "Rerun the Release workflow's images job: gh run rerun <run id> --failed"
    done
    echo "$ref: linux/amd64 linux/arm64"
  done

  git worktree remove --force "$dir" 2>/dev/null || true
  git branch -D "$branch" >/dev/null 2>&1 || true
  printf '\nReleased %s.\n' "$tag"
}

dry_run=false
version=
for arg in "$@"; do
  case $arg in
    --dry-run) dry_run=true ;;
    -*) echo "Usage: sh scripts/release.sh [--dry-run] [X.Y.Z]" >&2; exit 2 ;;
    *) [ -z "$version" ] || { echo "Usage: sh scripts/release.sh [--dry-run] [X.Y.Z]" >&2; exit 2; }; version=${arg#v} ;;
  esac
done
if [ -n "$version" ] && ! printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  stop "$version is not X.Y.Z" "Pass a plain version such as 0.6.0, or none to let the script choose."
fi

git fetch --quiet --tags origin ||
  stop "git could not fetch origin" "Check your network and that origin is the pumpkit repository, then run it again."
commit=$(git rev-parse --verify --quiet "origin/main^{commit}") ||
  stop "origin/main not found" "Check that origin is the pumpkit repository, then run it again."

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git show "$commit:CHANGELOG.md" >"$work/changelog" 2>/dev/null ||
  stop "CHANGELOG.md not found at origin/main" "Check that origin is the pumpkit repository."

latest=$(sed -n 's/^## \[\([0-9][0-9.]*\)\].*/\1/p' "$work/changelog" | head -1)
if [ -n "$latest" ] && [ -z "$(git ls-remote --tags origin "refs/tags/v$latest")" ]; then
  printf '\n%s is merged but not tagged.\n' "$latest"
  [ "$dry_run" = false ] || { echo "Dry run: a real run would tag v$latest."; exit 0; }
  dir=$(cd "$(git rev-parse --git-common-dir)/.." && pwd)/.claude/worktrees/release-v$latest
  branch=release/v$latest
  tag_and_check "$latest"
  exit 0
fi

step "Merged PRs since the last release"
published=$(gh release view --json publishedAt -q .publishedAt 2>/dev/null || true)
[ -n "$published" ] ||
  stop "gh found no published release to count PRs from" "Run gh auth status, and check gh release list."
gh pr list --state merged --base main --limit 200 --json number,title,labels \
  --search "merged:>$published" \
  -q '.[] | select(.title | startswith("Release ") | not) | "\(.number)\t\([.labels[].name] | index("no-changelog") != null)\t\(.title)"' >"$work/prs"

missing=
while IFS="$(printf '\t')" read -r number exempt title; do
  [ -n "$number" ] || continue
  if [ "$exempt" = true ]; then
    printf '#%s %s (no-changelog)\n' "$number" "$title"
  elif gh pr view "$number" --json files -q '.files[].path' | grep -qx CHANGELOG.md; then
    printf '#%s %s\n' "$number" "$title"
  else
    printf '#%s %s (NO CHANGELOG ENTRY)\n' "$number" "$title"
    missing="$missing #$number"
  fi
done <"$work/prs"
[ -s "$work/prs" ] || echo "none"
[ -z "$missing" ] ||
  stop "these merged PRs have no CHANGELOG entry and no no-changelog label:$missing" "Add their entries under ## [Unreleased] in a PR (or label them no-changelog), merge it, then run it again."

sh "$scripts_dir/release-notes.sh" Unreleased "$work/changelog" >"$work/unreleased" 2>/dev/null ||
  stop "## [Unreleased] in CHANGELOG.md has no entries, so there is nothing to release" "Merge the work to release first, with its CHANGELOG entry."

# Before 1.0, anything a User or Self-hoster must read about is a minor; only fixes make a patch.
if grep -Eq '^### (Added|Changed|Removed)|\*\*Upgrade notes:\*\*' "$work/unreleased"; then
  bump=minor
else
  bump="patch"
fi
if [ -z "$version" ]; then
  [ -n "$latest" ] || stop "CHANGELOG.md has no released version to count from" "Pass the version: sh scripts/release.sh X.Y.Z"
  major=${latest%%.*}
  rest=${latest#*.}
  minor=${rest%%.*}
  fix=${rest#*.}
  if [ "$bump" = minor ]; then
    version=$major.$((minor + 1)).0
  else
    version=$major.$minor.$((fix + 1))
  fi
  printf '\nVersion: %s (%s after %s)\n' "$version" "$bump" "$latest"
else
  printf '\nVersion: %s (given; the rule would choose a %s after %s)\n' "$version" "$bump" "$latest"
fi

if [ "$dry_run" = true ]; then
  echo "Dry run: nothing was changed."
  exit 0
fi

branch=release/v$version
tag=v$version
common=$(cd "$(git rev-parse --git-common-dir)/.." && pwd)
dir=$common/.claude/worktrees/release-v$version

step "Worktree $dir"
# A release branch already on origin carries the release commit and any fix pushed from another checkout.
remote=$(git rev-parse --verify --quiet "refs/remotes/origin/$branch^{commit}") || remote=
if [ ! -d "$dir" ]; then
  git rev-parse --verify --quiet "refs/heads/$branch" >/dev/null &&
    stop "the branch $branch exists without a worktree at $dir" "Delete it with git branch -D $branch if it is stale, then run it again."
  git worktree add --quiet -b "$branch" "$dir" "${remote:-$commit}" ||
    stop "git could not add the worktree $dir" "Fix what git printed above, then run it again."
fi
[ -z "$(git -C "$dir" status --porcelain)" ] ||
  stop "the worktree $dir has uncommitted changes" "Commit or discard them there, then run it again."
if [ -n "$remote" ]; then
  git -C "$dir" merge --quiet --ff-only "$remote" ||
    stop "the worktree $dir has commits that origin/$branch does not, and git could not fast-forward it" "Rebase them onto origin/$branch with git -C $dir rebase origin/$branch, or drop them with git -C $dir reset --hard origin/$branch, then run it again."
fi

step "Release commit"
if ! git -C "$dir" log --format=%s "$commit..HEAD" | grep -qx "Release $version"; then
  (cd "$dir" && sh scripts/prepare-release.sh "$version" >"$work/notes") ||
    stop "prepare-release.sh refused $version" "Read its message above, and pass another version if it is the version that is wrong."
  git -C "$dir" commit --quiet -am "Release $version"
fi
git -C "$dir" push --quiet -u origin "$branch" ||
  stop "pushing $branch failed" "Fix what git printed above, then run it again."

step "Pull request"
pr=$(gh pr list --head "$branch" --state open --json number -q '.[0].number')
if [ -z "$pr" ]; then
  sh "$scripts_dir/release-notes.sh" "$version" "$dir/CHANGELOG.md" >"$work/body"
  url=$(gh pr create --head "$branch" --base main --title "Release $version" --body-file "$work/body") ||
    stop "gh could not open the Release PR" "Open it by hand with the title 'Release $version', then run it again."
  pr=${url##*/}
fi
echo "PR #$pr"
head=$(git -C "$dir" rev-parse HEAD)
# The commit whose review this run started or found; empty while a failed gh read leaves that unknown.
reviewed=

step "Auto-merge"
# GitHub merges the PR once every required check passes, review included, even if this run dies before then.
gh pr merge "$pr" --auto --squash --delete-branch >/dev/null ||
  [ "$(gh pr view "$pr" --json state -q .state)" = MERGED ] ||
  stop "gh could not turn on auto-merge for PR #$pr" "Run gh pr merge $pr --auto --squash --delete-branch, then run this again."
echo "auto-merge on for PR #$pr"

step "Review"
# The review takes as long as CI, so it runs alongside it.
if ensure_review; then
  reviewed=$head
else
  echo "gh could not read the review on $head; the wait tries again"
fi

step "Waiting for GitHub to merge PR #$pr"
# Each read is guarded: a failed poll, such as a network blip, reads as still waiting.
deadline=$(($(date +%s) + wait_limit))
while :; do
  state=$(gh pr view "$pr" --json state -q .state 2>/dev/null) || state=
  [ "$state" != MERGED ] || break
  # A push to the release branch during the wait moves the PR to a commit that needs its own review.
  current=$(gh pr view "$pr" --json headRefOid -q .headRefOid 2>/dev/null) || current=
  if [ -n "$current" ] && [ "$current" != "$head" ]; then
    head=$current
    reviewed=
    echo "PR #$pr moved to $head"
  fi
  if [ "$reviewed" != "$head" ] && ensure_review; then
    reviewed=$head
  fi
  # gh pr checks exits non-zero while checks are pending or none are reported yet, so its output decides.
  failed=$(gh pr checks "$pr" --json name,bucket -q '.[] | select(.name != "review") | select(.bucket == "fail" or .bucket == "cancel") | .name' 2>/dev/null || true)
  [ -z "$failed" ] ||
    stop "these checks on PR #$pr did not pass: $(echo "$failed" | tr '\n' ' ')" "Read them with gh pr checks $pr, push a fix to $branch, and run this again; it starts the review on the new commit."
  if [ "$reviewed" = "$head" ]; then
    # The run is read before the status, so a completed run's final status is already visible.
    run=$(review_run 2>/dev/null) || run=
    review=$(review_status 2>/dev/null) || review=
    if is_final "$review"; then
      [ "$review" = success ] ||
        stop "the review of PR #$pr ended $review" "Read its comment on the PR, fix the findings, push to $branch, and run this again."
    else
      [ "$run" != completed ] ||
        stop "the review run on PR #$pr ended without a final review status" "Read it with gh run list --workflow sdlc-review-llm.yml --branch $branch, fix the cause, and run this again; it starts a new review."
    fi
  fi
  [ "$(date +%s)" -lt "$deadline" ] ||
    stop "PR #$pr is not merged after $((wait_limit / 60)) minutes" "Auto-merge is still on, so GitHub merges it once its checks and review pass. See where they stand with gh pr checks $pr, and run this again later to tag it."
  sleep "$poll"
done
echo "PR #$pr merged"

tag_and_check "$version"
