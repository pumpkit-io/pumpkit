#!/bin/sh
# Checks prepare-release.sh, tag-release.sh, release.sh and check-changelog-entry.sh against throwaway git repos.
# Usage: sh scripts/check-release-scripts.sh
set -eu

scripts=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Isolates git from the user's config (signing, hooks, default branch).
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=test@example.com GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=test@example.com
export RELEASE_DATE=2026-11-02 RELEASE_WATCH=false

failures=0
fail() {
  printf 'FAIL: %s\n' "$*"
  failures=$((failures + 1))
}
pass() {
  printf 'ok: %s\n' "$*"
}

# Usage: run COMMAND... Sets $status, with stdout in $out and stderr in $err.
out=$work/out
err=$work/err
run() {
  set +e
  "$@" >"$out" 2>"$err"
  status=$?
  set -e
}

# Usage: new_repo DIR. A main branch with a CHANGELOG at 0.1.0 plus Unreleased entries, pushed to DIR.git.
new_repo() {
  git init -q --bare -b main "$1.git"
  git init -q -b main "$1"
  cat >"$1/CHANGELOG.md" <<'EOF'
# Changelog

## [Unreleased]

### Fixed

- A fix.

## [0.1.0] - 2026-10-12

- First.
EOF
  printf 'APP=pumpkit\nPUMPKIT_VERSION=0.1.0\n' >"$1/.env.example"
  git -C "$1" add -A
  git -C "$1" commit -q -m init
  git -C "$1" remote add origin "$1.git"
  git -C "$1" push -q origin main
}

# prepare-release.sh

new_repo "$work/prep"
cd "$work/prep"
run sh "$scripts/prepare-release.sh" 0.2.0
cat >"$work/expected-changelog" <<'EOF'
# Changelog

## [Unreleased]

## [0.2.0] - 2026-11-02

### Fixed

- A fix.

## [0.1.0] - 2026-10-12

- First.
EOF
if [ "$status" -eq 0 ] && cmp -s CHANGELOG.md "$work/expected-changelog" && grep -qx 'PUMPKIT_VERSION=0.2.0' .env.example && grep -qx 'APP=pumpkit' .env.example; then
  pass "prepare-release moves Unreleased under the new version and sets PUMPKIT_VERSION"
else
  fail "prepare-release 0.2.0: status $status, $(cat "$err")"
  diff "$work/expected-changelog" CHANGELOG.md || true
fi

run sh "$scripts/prepare-release.sh" 0.3.0
if [ "$status" -ne 0 ] && grep -q 'empty' "$err"; then
  pass "prepare-release refuses an empty Unreleased section"
else
  fail "expected prepare-release to refuse an empty Unreleased, got status $status"
fi

git checkout -q -- .
run sh "$scripts/prepare-release.sh" 0.1.0
if [ "$status" -ne 0 ] && grep -q '0\.1\.0' "$err"; then
  pass "prepare-release refuses a version already in the CHANGELOG"
else
  fail "expected prepare-release to refuse 0.1.0, got status $status"
fi

run sh "$scripts/prepare-release.sh" 0.0.9
if [ "$status" -ne 0 ] && grep -q 'not above' "$err"; then
  pass "prepare-release refuses a version below the latest release"
else
  fail "expected prepare-release to refuse 0.0.9, got status $status"
fi

run sh "$scripts/prepare-release.sh" 0.2.0-rc.1
if [ "$status" -ne 0 ] && [ -z "$(git status --porcelain)" ]; then
  pass "prepare-release refuses a pre-release version and changes nothing"
else
  fail "expected prepare-release to refuse 0.2.0-rc.1, got status $status"
fi

# check-changelog-entry.sh

base=$(git rev-parse HEAD)
run sh "$scripts/check-changelog-entry.sh" "$base"
if [ "$status" -ne 0 ] && grep -q 'no-changelog' "$err"; then
  pass "check-changelog-entry fails a PR that leaves CHANGELOG.md alone"
else
  fail "expected check-changelog-entry to fail an unchanged CHANGELOG, got status $status"
fi

awk '{ print } $0 == "- A fix." { print "- Another fix." }' CHANGELOG.md >"$work/c" && cat "$work/c" >CHANGELOG.md
git commit -q -am "add an entry"
run sh "$scripts/check-changelog-entry.sh" "$base"
if [ "$status" -eq 0 ]; then
  pass "check-changelog-entry passes a PR that adds an Unreleased entry"
else
  fail "expected check-changelog-entry to pass a new Unreleased entry: $(cat "$err")"
fi

git reset -q --hard "$base"
printf '%s\n' '- A change. **Upgrade notes:** Nothing to do by hand; the backend applies the migration on start.' >"$work/entry"
awk -v f="$work/entry" '{ print } $0 == "- A fix." { while ((getline l < f) > 0) print l }' CHANGELOG.md >"$work/c" && cat "$work/c" >CHANGELOG.md
git commit -q -am "add an entry with empty upgrade notes"
run sh "$scripts/check-changelog-entry.sh" "$base"
if [ "$status" -ne 0 ] && grep -q 'Upgrade notes' "$err"; then
  pass "check-changelog-entry rejects Upgrade notes that say there is nothing to do by hand"
else
  fail "expected check-changelog-entry to reject empty Upgrade notes, got status $status"
fi

git reset -q --hard "$base"
printf '%s\n' '- A change. **Upgrade notes:** If `.env` sets `OLD`, rename it to `NEW`.' >"$work/entry"
awk -v f="$work/entry" '{ print } $0 == "- A fix." { while ((getline l < f) > 0) print l }' CHANGELOG.md >"$work/c" && cat "$work/c" >CHANGELOG.md
git commit -q -am "add an entry with real upgrade notes"
run sh "$scripts/check-changelog-entry.sh" "$base"
if [ "$status" -eq 0 ]; then
  pass "check-changelog-entry passes Upgrade notes that name a step"
else
  fail "expected check-changelog-entry to pass real Upgrade notes: $(cat "$err")"
fi

git reset -q --hard "$base"
sh "$scripts/prepare-release.sh" 0.2.0 >/dev/null
git commit -q -am "Release 0.2.0"
run sh "$scripts/check-changelog-entry.sh" "$base"
if [ "$status" -eq 0 ] && grep -q 'release section' "$out"; then
  pass "check-changelog-entry passes a release PR"
else
  fail "expected check-changelog-entry to pass a release PR: $(cat "$err")"
fi

# tag-release.sh, on the release commit just made

git push -q origin main

run sh "$scripts/tag-release.sh" 0.3.0
if [ "$status" -ne 0 ] && grep -q 'PUMPKIT_VERSION=0.2.0' "$err"; then
  pass "tag-release refuses a version origin/main doesn't set"
else
  fail "expected tag-release to refuse 0.3.0, got status $status"
fi

# A clone elsewhere pushes a later commit, so this checkout is behind origin/main, on another branch and dirty.
git clone -q "$work/prep.git" "$work/pusher"
git -C "$work/pusher" commit -q --allow-empty -m "after the release"
git -C "$work/pusher" push -q origin main
git checkout -q -b other
echo dirty >>CHANGELOG.md

run sh "$scripts/tag-release.sh" 0.2.0
if [ "$status" -eq 0 ] && [ "$(git --git-dir="$work/prep.git" tag)" = v0.2.0 ] &&
  [ "$(git --git-dir="$work/prep.git" cat-file -t v0.2.0)" = tag ] &&
  [ "$(git --git-dir="$work/prep.git" rev-parse 'v0.2.0^{commit}')" = "$(git --git-dir="$work/prep.git" rev-parse main)" ]; then
  pass "tag-release tags origin/main as an annotated tag, whatever the checkout"
else
  fail "expected tag-release to tag origin/main: status $status, $(cat "$err")"
fi

run sh "$scripts/tag-release.sh" 0.2.0
if [ "$status" -ne 0 ] && grep -q 'already exists' "$err"; then
  pass "tag-release refuses a tag that exists"
else
  fail "expected tag-release to refuse an existing tag, got status $status"
fi

# The watch, with a gh stub whose run watch always fails like a dropped connection and whose run view answers from $GH_CONCLUSION.
mkdir "$work/bin"
cat >"$work/bin/gh" <<'STUB'
#!/bin/sh
case "$1 $2" in
  "run list") echo 42 ;;
  "run watch") exit 1 ;;
  "run view")
    case "$*" in
      *conclusion*) cat "$GH_CONCLUSION" ;;
      *) echo https://github.example/runs/42 ;;
    esac ;;
  "release view") echo "release shown" ;;
esac
STUB
chmod +x "$work/bin/gh"
export GH_CONCLUSION="$work/conclusion"

# Usage: watch_release VERSION CONCLUSION. Releases VERSION from the clone, then tags it with the watch on.
watch_release() {
  (
    cd "$work/pusher"
    git pull -q --ff-only origin main
    sh "$scripts/prepare-release.sh" "$1" >/dev/null
    git commit -q -am "Release $1"
    git push -q origin main
  )
  printf '%s' "$2" >"$GH_CONCLUSION"
  RELEASE_WATCH=true RELEASE_POLL_SECONDS=0 PATH="$work/bin:$PATH" run sh "$scripts/tag-release.sh" "$1"
}

# prepare-release needs entries under Unreleased each time.
add_entry() {
  (
    cd "$work/pusher"
    git pull -q --ff-only origin main
    awk '{ print } $0 == "## [Unreleased]" { print ""; print "### Fixed"; print ""; print "- Entry." }' CHANGELOG.md >"$work/c"
    cat "$work/c" >CHANGELOG.md
    git commit -q -am "entry"
    git push -q origin main
  )
}

add_entry
watch_release 0.2.1 success
if [ "$status" -eq 0 ] && ! grep -qi 'failed' "$err" && grep -q 'release shown' "$out"; then
  pass "tag-release ends on a success conclusion after a dropped watch"
else
  fail "expected a dropped watch on a successful run to pass: status $status, $(cat "$err")"
fi

add_entry
watch_release 0.2.2 failure
if [ "$status" -ne 0 ] && grep -q 'ended failure' "$err"; then
  pass "tag-release reports a failed run"
else
  fail "expected tag-release to report a failed run: status $status, $(cat "$err")"
fi

add_entry
watch_release 0.2.3 cancelled
if [ "$status" -ne 0 ] && grep -q 'ended cancelled' "$err"; then
  pass "tag-release reports a cancelled run"
else
  fail "expected tag-release to report a cancelled run: status $status, $(cat "$err")"
fi

add_entry
watch_release 0.2.4 ""
if [ "$status" -ne 0 ] && grep -q 'lost its connection' "$err" && grep -q 'github.example/runs/42' "$err" && ! grep -q 'workflow failed' "$err"; then
  pass "tag-release says the watch lost its connection, with the run URL, when the conclusion is unknown"
else
  fail "expected a lost-connection message: status $status, $(cat "$err")"
fi

# release.sh --dry-run, with a gh stub answering from $GH_PRS (tab-separated number, exempt, title) and $GH_FILES/<number> (the files a PR changed).
mkdir "$work/ghfiles" "$work/relbin"
cat >"$work/relbin/gh" <<'STUB'
#!/bin/sh
case "$1 $2" in
  "release view") echo 2026-10-12T00:00:00Z ;;
  "pr list") cat "$GH_PRS" ;;
  "pr view") cat "$GH_FILES/$3" ;;
esac
STUB
chmod +x "$work/relbin/gh"
export GH_PRS="$work/prs" GH_FILES="$work/ghfiles"
printf 'CHANGELOG.md\n' >"$work/ghfiles/7"
printf 'backend/x.py\n' >"$work/ghfiles/8"
printf '7\tfalse\tFix a thing\n' >"$GH_PRS"

# Usage: release_repo UNRELEASED_FILE. A repo at 0.1.0, tagged, whose Unreleased section is the file's content; leaves the cwd in a clone of it.
release_repo() {
  cd "$work"
  rm -rf "$work/rel" "$work/rel.git" "$work/relclone"
  new_repo "$work/rel"
  {
    sed -n '1,/^## \[Unreleased\]/p' "$work/rel/CHANGELOG.md"
    cat "$1"
    echo
    sed -n '/^## \[0.1.0\]/,$p' "$work/rel/CHANGELOG.md"
  } >"$work/rel-changelog"
  cp "$work/rel-changelog" "$work/rel/CHANGELOG.md"
  git -C "$work/rel" commit -q --allow-empty -am "unreleased"
  git -C "$work/rel" tag -a v0.1.0 -m v0.1.0
  git -C "$work/rel" push -q origin main v0.1.0
  git clone -q "$work/rel.git" "$work/relclone"
  cd "$work/relclone"
}

# Usage: release_dry_run ARGS... Runs release.sh --dry-run in the current repo with the stubs first on PATH.
release_dry_run() {
  PATH="$work/relbin:$PATH" run sh "$scripts/release.sh" --dry-run "$@"
}

printf '\n### Fixed\n\n- A fix.\n' >"$work/u-fixed"
release_repo "$work/u-fixed"
release_dry_run
if [ "$status" -eq 0 ] && grep -q 'Version: 0.1.1 (patch after 0.1.0)' "$out" && grep -q '#7 Fix a thing' "$out"; then
  pass "release dry run chooses a patch for Fixed entries and lists the PRs"
else
  fail "expected a 0.1.1 patch: status $status, $(cat "$out" "$err")"
fi
if [ -z "$(git worktree list | sed 1d)" ] && [ -z "$(git branch --list 'release/*')" ]; then
  pass "release dry run adds no worktree or branch"
else
  fail "expected the dry run to change nothing: $(git worktree list)"
fi

release_dry_run 0.1.5
if [ "$status" -eq 0 ] && grep -q 'Version: 0.1.5 (given; the rule would choose a patch after 0.1.0)' "$out"; then
  pass "release dry run takes the version it is given"
else
  fail "expected the given version: status $status, $(cat "$out" "$err")"
fi

for heading in Added Changed Removed; do
  printf '\n### Fixed\n\n- A fix.\n\n### %s\n\n- A change.\n' "$heading" >"$work/u-minor"
  release_repo "$work/u-minor"
  release_dry_run
  if [ "$status" -eq 0 ] && grep -q 'Version: 0.2.0 (minor after 0.1.0)' "$out"; then
    pass "release dry run chooses a minor for $heading"
  else
    fail "expected a 0.2.0 minor for $heading: status $status, $(cat "$out" "$err")"
  fi
done

printf '\n### Fixed\n\n- A fix. **Upgrade notes:** Rename `OLD` to `NEW` in `.env`.\n' >"$work/u-notes"
release_repo "$work/u-notes"
release_dry_run
if [ "$status" -eq 0 ] && grep -q 'Version: 0.2.0 (minor after 0.1.0)' "$out"; then
  pass "release dry run chooses a minor for Upgrade notes"
else
  fail "expected a 0.2.0 minor for Upgrade notes: status $status, $(cat "$out" "$err")"
fi

release_repo "$work/u-fixed"
printf '7\tfalse\tFix a thing\n8\tfalse\tForgot the entry\n9\ttrue\tTidy up\n' >"$GH_PRS"
release_dry_run
if [ "$status" -ne 0 ] && grep -q '^STOPPED: .*#8' "$err" && ! grep -q '#7$' "$err" && grep -q '^NEXT:' "$err" && grep -q '#9 Tidy up (no-changelog)' "$out"; then
  pass "release stops on a merged PR with no entry and no no-changelog label"
else
  fail "expected a stop naming #8: status $status, $(cat "$out" "$err")"
fi
printf '7\tfalse\tFix a thing\n' >"$GH_PRS"

printf '\n' >"$work/u-empty"
release_repo "$work/u-empty"
release_dry_run
if [ "$status" -ne 0 ] && grep -q '^STOPPED: .*nothing to release' "$err" && grep -q '^NEXT:' "$err"; then
  pass "release stops when Unreleased has no entries"
else
  fail "expected a nothing-to-release stop: status $status, $(cat "$out" "$err")"
fi

release_repo "$work/u-fixed"
git -C "$work/rel" tag -d v0.1.0 >/dev/null
git -C "$work/rel.git" tag -d v0.1.0 >/dev/null
git fetch -q --prune --prune-tags origin
release_dry_run
if [ "$status" -eq 0 ] && grep -q '0.1.0 is merged but not tagged' "$out"; then
  pass "release resumes at the tag when the latest release was merged but not tagged"
else
  fail "expected the resume message: status $status, $(cat "$out" "$err")"
fi

release_dry_run 1.2
if [ "$status" -ne 0 ] && grep -q '^STOPPED: 1.2 is not X.Y.Z' "$err"; then
  pass "release refuses a version that is not X.Y.Z"
else
  fail "expected a bad-version stop: status $status, $(cat "$err")"
fi

# release.sh past the PR, with a gh stub logging every call to $GH_LOG and answering from state files a case writes.
# $GH_PR_STATE, $GH_HEAD (the PR's head commit, the local release branch by default), $GH_CHECKS (JSON, empty for none reported),
# $GH_REVIEW (a commit's review status) and $GH_RUN (its review run's status) answer from FILE.N on the Nth read when it exists, else FILE;
# a file reading !fail makes that call fail like a dropped connection. $GH_REVIEW@SHA and $GH_RUN@SHA, when they exist, answer for that commit only.
# With $GH_REVIEW_CLOCK set, review and run reads share one count, so FILE.N is the Nth read of either and two files can change together.
# A dispatch posts its final status for the PR's head (the last headRefOid answered, else the local release branch), and its run reads queued once, then completed;
# status reads are logged with their answer.
mkdir "$work/prbin"
cat >"$work/prbin/gh" <<'STUB'
#!/bin/sh
echo "$*" >>"$GH_LOG"
# Usage: answer FILE [COUNTER]. COUNTER defaults to FILE.reads.
answer() {
  counter=${2:-$1.reads}
  n=$(($(cat "$counter" 2>/dev/null || echo 0) + 1))
  echo "$n" >"$counter"
  if [ -f "$1.$n" ]; then a=$(cat "$1.$n"); else a=$(cat "$1"); fi
  printf '%s' "$a" >"$1.last"
  [ "$a" != '!fail' ] || { echo "error connecting to api.github.com" >&2; exit 1; }
  printf '%s' "$a"
}
# Usage: answer_for SHA FILE.
answer_for() {
  if [ -e "$2@$1" ]; then f="$2@$1"; else f=$2; fi
  answer "$f" ${GH_REVIEW_CLOCK:+"$GH_REVIEW_CLOCK"}
}
release_branch_head() {
  git rev-parse "$(git for-each-ref --format='%(refname)' 'refs/heads/release/*' | head -1)"
}
query() {
  while [ $# -gt 0 ]; do
    [ "$1" != -q ] || { printf '%s' "$2"; return; }
    shift
  done
}
# What GitHub does on a merge: origin's main moves to the release branch, where tag-release.sh finds the release.
merge_on_github() {
  git push -q origin "$(release_branch_head):refs/heads/main"
}
case "$1 $2" in
  "release view") echo 2026-10-12T00:00:00Z ;;
  "pr list") case "$*" in *--head*) ;; *) cat "$GH_PRS" ;; esac ;;
  "pr view")
    case "$*" in
      *headRefOid*)
        [ -e "$GH_HEAD" ] || release_branch_head >"$GH_HEAD"
        answer "$GH_HEAD" ;;
      *state*)
        state=$(answer "$GH_PR_STATE") || exit 1
        [ "$state" != MERGED ] || merge_on_github
        printf '%s\n' "$state" ;;
      *) cat "$GH_FILES/$3" ;;
    esac ;;
  "pr create") echo https://github.example/pumpkit-io/pumpkit/pull/5 ;;
  "pr merge")
    case "$*" in
      *--auto*) ;;
      *)
        merge_on_github
        rm -f "$GH_PR_STATE".*
        printf MERGED >"$GH_PR_STATE" ;;
    esac ;;
  "pr checks")
    checks=$(answer "$GH_CHECKS") || exit 1
    [ -n "$checks" ] || { echo "no checks reported on the 'release' branch" >&2; exit 1; }
    printf '%s' "$checks" | jq -r "$(query "$@")"
    # Like gh, exits 8 while a check is pending.
    case $checks in *pending*) exit 8 ;; esac ;;
  "run list")
    case "$*" in
      *databaseId*) cat "$GH_RUN_ID" 2>/dev/null || true ;;
      *) sha=$*; sha=${sha#*--commit }; answer_for "${sha%% *}" "$GH_RUN" ;;
    esac ;;
  "workflow run")
    if [ -e "$GH_HEAD.last" ]; then sha=$(cat "$GH_HEAD.last"); else sha=$(release_branch_head); fi
    rm -f "$GH_REVIEW@$sha".* "$GH_RUN@$sha".*
    cp "$GH_REVIEW_FINAL_STATUS" "$GH_REVIEW@$sha"
    printf queued >"$GH_RUN@$sha.1"
    printf completed >"$GH_RUN@$sha"
    echo $(($(cat "$GH_RUN_ID" 2>/dev/null || echo 0) + 1)) >"$GH_RUN_ID" ;;
  "api "*/statuses)
    sha=${2%/statuses}
    sha=${sha##*/}
    review=$(answer_for "$sha" "$GH_REVIEW") || exit 1
    echo "review of $sha: $review" >>"$GH_LOG"
    printf '%s' "$review" ;;
  "api "*) cat "$GH_ADMIN" ;;
esac
STUB
cat >"$work/prbin/docker" <<'STUB'
#!/bin/sh
printf 'Name:      %s\n\nManifests:\n  Platform:    linux/amd64\n  Platform:    linux/arm64\n' "$4"
STUB
chmod +x "$work/prbin/gh" "$work/prbin/docker"
export GH_LOG="$work/gh-log" GH_PR_STATE="$work/gh-prstate" GH_HEAD="$work/gh-head" GH_CHECKS="$work/gh-checks" GH_REVIEW="$work/gh-review" GH_RUN="$work/gh-run"
export GH_RUN_ID="$work/gh-runid" GH_ADMIN="$work/gh-admin" GH_REVIEW_FINAL_STATUS="$work/gh-review-final-status"

# Usage: release_case. A fresh repo, and the stub's state reset to an admin login, an open PR whose checks pass, no review yet,
# and a review that ends success once dispatched. The PR stays open until the case changes $GH_PR_STATE, as merges_on_read does.
release_case() {
  release_repo "$work/u-fixed"
  mkdir scripts
  cp "$scripts/prepare-release.sh" "$scripts/release-notes.sh" scripts/
  git add scripts
  git commit -q -m scripts
  git push -q origin main
  rm -f "$work"/gh-*
  printf OPEN >"$GH_PR_STATE"
  printf '[{"name":"backend","bucket":"pass"},{"name":"e2e","bucket":"skipping"},{"name":"review","bucket":"pending"}]' >"$GH_CHECKS"
  : >"$GH_REVIEW"
  : >"$GH_RUN"
  echo true >"$GH_ADMIN"
  printf success >"$GH_REVIEW_FINAL_STATUS"
}

# Usage: release_run WAIT_SECONDS. Runs release.sh in the current repo with the stubs first on PATH.
# Every case that should not time out passes a minute, so a broken one stops instead of hanging.
release_run() {
  run env RELEASE_POLL_SECONDS=0 RELEASE_WAIT_SECONDS="$1" PATH="$work/prbin:$PATH" sh "$scripts/release.sh"
}

# Usage: merges_on_read N. GitHub merges the PR on its own, so the Nth read of its state and every later one say MERGED.
merges_on_read() {
  i=1
  while [ "$i" -lt "$1" ]; do
    printf OPEN >"$GH_PR_STATE.$i"
    i=$((i + 1))
  done
  printf MERGED >"$GH_PR_STATE"
}

# Usage: merged_by_hand. Succeeds when the log shows a merge call without --auto.
merged_by_hand() {
  grep '^pr merge' "$GH_LOG" | grep -qv -- '--auto'
}

released() {
  [ "$status" -eq 0 ] && grep -q '^Released v0.1.1\.$' "$out" &&
    [ "$(git --git-dir="$work/rel.git" rev-parse 'v0.1.1^{commit}')" = "$(git --git-dir="$work/rel.git" rev-parse main)" ]
}

release_case
merges_on_read 3
release_run 60
if released && ! merged_by_hand && grep -q 'pumpkit-web:0.1.1: linux/amd64 linux/arm64' "$out"; then
  pass "release tags and checks the images once GitHub merges the PR, without merging it itself"
else
  fail "expected Released v0.1.1 with no merge call: status $status, $(cat "$out" "$err" "$GH_LOG")"
fi
if [ "$(grep -A1 '^pr create' "$GH_LOG" | sed -n 2p)" = 'pr merge 5 --auto --squash --delete-branch' ]; then
  pass "release turns on auto-merge right after opening the PR"
else
  fail "expected gh pr merge --auto after gh pr create: $(cat "$GH_LOG")"
fi
first_auto=$(grep -n -- '^pr merge 5 --auto' "$GH_LOG" | head -1 | cut -d: -f1)
first_dispatch=$(grep -n '^workflow run sdlc-review-llm.yml' "$GH_LOG" | head -1 | cut -d: -f1)
first_checks=$(grep -n '^pr checks' "$GH_LOG" | head -1 | cut -d: -f1)
if [ "$(grep -c '^workflow run sdlc-review-llm.yml' "$GH_LOG")" = 1 ] &&
  [ "${first_auto:-99999}" -lt "${first_dispatch:-0}" ] && [ "${first_dispatch:-99999}" -lt "${first_checks:-0}" ]; then
  pass "release starts the review once, right after turning on auto-merge"
else
  fail "expected one review dispatch between auto-merge and the checks: $(cat "$GH_LOG")"
fi

release_case
: >"$GH_CHECKS.1"
: >"$GH_CHECKS.2"
printf '[{"name":"backend","bucket":"pending"},{"name":"review","bucket":"pending"}]' >"$GH_CHECKS.3"
merges_on_read 5
release_run 60
if released && [ "$(grep -c '^pr checks' "$GH_LOG")" -ge 3 ]; then
  pass "release keeps waiting while no checks are reported, then releases"
else
  fail "expected release to wait through no checks: status $status, $(cat "$out" "$err")"
fi

release_case
printf '[{"name":"backend","bucket":"pass"},{"name":"frontend","bucket":"fail"},{"name":"review","bucket":"pending"}]' >"$GH_CHECKS"
release_run 60
if [ "$status" -ne 0 ] && grep -q '^STOPPED: these checks on PR #5 did not pass: frontend' "$err" && grep -q '^NEXT:' "$err" &&
  ! merged_by_hand && [ -z "$(git --git-dir="$work/rel.git" tag -l v0.1.1)" ]; then
  pass "release stops naming a failing check, without merging"
else
  fail "expected a stop naming frontend: status $status, $(cat "$err")"
fi

release_case
printf failure >"$GH_REVIEW_FINAL_STATUS"
release_run 60
if [ "$status" -ne 0 ] && grep -q '^STOPPED: the review of PR #5 ended failure' "$err" && grep -q '^NEXT: Read its comment on the PR' "$err" && ! merged_by_hand; then
  pass "release stops when the review fails, pointing at its comment"
else
  fail "expected a failed-review stop: status $status, $(cat "$err")"
fi

release_case
printf error >"$GH_REVIEW_FINAL_STATUS"
release_run 60
if [ "$status" -ne 0 ] && grep -q '^STOPPED: the review of PR #5 ended error' "$err" &&
  grep -q '^NEXT: Read its comment on PR #5.*gh run list.*gh workflow run sdlc-review-llm.yml --ref release/v0.1.1' "$err" && ! merged_by_hand; then
  pass "release stops when the review ends error, saying to start it again"
else
  fail "expected an errored-review stop: status $status, $(cat "$err")"
fi

# A rerun after an errored review, started again by hand, finds the new run going while the commit still shows the old error.
release_case
printf in_progress >"$GH_RUN.1"
printf error >"$GH_REVIEW.2"
printf in_progress >"$GH_RUN.3"
printf error >"$GH_REVIEW.4"
printf completed >"$GH_RUN"
printf success >"$GH_REVIEW"
merges_on_read 3
GH_REVIEW_CLOCK="$work/gh-review-clock" release_run 60
if released && ! grep -q '^workflow run' "$GH_LOG"; then
  pass "release waits on a review run still going rather than an old final status"
else
  fail "expected the wait to ignore the old error: status $status, $(cat "$out" "$err" "$GH_LOG")"
fi

# The review run seen in progress when the PR opens dies before posting a status.
release_case
printf pending >"$GH_REVIEW"
printf in_progress >"$GH_RUN.1"
printf completed >"$GH_RUN"
release_run 60
if [ "$status" -ne 0 ] && grep -q '^STOPPED: the review run on PR #5 ended without a final review status' "$err" &&
  grep -q '^NEXT: .*starts a new review' "$err" && ! grep -q '^workflow run' "$GH_LOG" && ! merged_by_hand; then
  pass "release stops when the review run ends without a final status"
else
  fail "expected a dead-review stop: status $status, $(cat "$err")"
fi

# A rerun after a review run that died, leaving the status pending, starts a new one instead of waiting on the dead one.
release_case
printf pending >"$GH_REVIEW"
printf completed >"$GH_RUN"
merges_on_read 2
release_run 60
if released && [ "$(grep -c '^workflow run sdlc-review-llm.yml' "$GH_LOG")" = 1 ]; then
  pass "release starts the review again when the last run ended without a final status"
else
  fail "expected a new review dispatch: status $status, $(cat "$err" "$GH_LOG")"
fi

release_case
printf pending >"$GH_REVIEW"
printf in_progress >"$GH_RUN"
merges_on_read 2
release_run 60
if released && ! grep -q '^workflow run' "$GH_LOG"; then
  pass "release leaves a review run in progress alone"
else
  fail "expected no dispatch while a review runs: status $status, $(cat "$err" "$GH_LOG")"
fi

release_case
release_run 0
if [ "$status" -ne 0 ] && grep -q '^STOPPED: PR #5 is not merged after' "$err" && grep -q '^NEXT: Auto-merge is still on' "$err" && ! merged_by_hand; then
  pass "release stops when the wait runs out, saying auto-merge is still on"
else
  fail "expected a timeout stop: status $status, $(cat "$err")"
fi
git push -q origin release/v0.1.1:main
: >"$GH_LOG"
release_run 60
if released && ! grep -q '^pr ' "$GH_LOG"; then
  pass "a rerun after GitHub merged the PR goes straight to the tag"
else
  fail "expected the rerun to tag: status $status, $(cat "$out" "$err" "$GH_LOG")"
fi

release_case
echo false >"$GH_ADMIN"
release_run 60
if [ "$status" -ne 0 ] && grep -q '^STOPPED: your gh login is not an admin' "$err" &&
  grep -q '^NEXT: .*gh workflow run sdlc-review-llm.yml --ref release/v0.1.1' "$err" &&
  grep -q -- '^pr merge 5 --auto' "$GH_LOG" && ! grep -q '^workflow run' "$GH_LOG"; then
  pass "a login that is not an admin turns on auto-merge, then asks a maintainer to start the review"
else
  fail "expected auto-merge and a not-admin stop: status $status, $(cat "$err" "$GH_LOG")"
fi

release_case
printf success >"$GH_REVIEW"
printf '!fail' >"$GH_REVIEW.2"
printf completed >"$GH_RUN"
printf '!fail' >"$GH_RUN.1"
printf '!fail' >"$GH_CHECKS.1"
printf '!fail' >"$GH_PR_STATE.1"
printf MERGED >"$GH_PR_STATE"
release_run 60
if released; then
  pass "release reads a failed gh call in the wait as still waiting"
else
  fail "expected failed polls to keep the wait going: status $status, $(cat "$out" "$err")"
fi

# A rerun after a fix is pushed to the release branch from another checkout starts the review on the fix and releases.
release_case
printf '[{"name":"backend","bucket":"pass"},{"name":"frontend","bucket":"fail"},{"name":"review","bucket":"pending"}]' >"$GH_CHECKS"
release_run 60
rm -rf "$work/fixer"
git clone -q -b release/v0.1.1 "$work/rel.git" "$work/fixer"
git -C "$work/fixer" commit -q --allow-empty -m "fix the frontend"
git -C "$work/fixer" push -q origin release/v0.1.1
fix=$(git -C "$work/fixer" rev-parse HEAD)
rm -f "$work"/gh-checks* "$work"/gh-prstate* "$GH_HEAD" "$GH_LOG"
printf '[{"name":"backend","bucket":"pass"},{"name":"frontend","bucket":"pass"},{"name":"review","bucket":"pending"}]' >"$GH_CHECKS"
: >"$GH_REVIEW@$fix"
: >"$GH_RUN@$fix"
merges_on_read 3
release_run 60
if released && grep -q "^review started on $fix\$" "$out" && [ "$(grep -c '^workflow run sdlc-review-llm.yml' "$GH_LOG")" = 1 ] &&
  [ "$(git --git-dir="$work/rel.git" log -1 --format=%s main)" = "fix the frontend" ]; then
  pass "a rerun after a fix pushed to the release branch reviews the fix and releases"
else
  fail "expected the rerun to pick up the fix: status $status, $(cat "$out" "$err" "$GH_LOG")"
fi

# A commit pushed to the release branch during the wait gets its own review; the first commit's failed review no longer counts.
release_case
new_head=0123456789abcdef0123456789abcdef01234567
printf failure >"$GH_REVIEW"
printf completed >"$GH_RUN"
printf '%s' "$new_head" >"$GH_HEAD"
: >"$GH_REVIEW@$new_head"
: >"$GH_RUN@$new_head"
merges_on_read 4
release_run 60
merged_at=$(grep -n '^pr view 5 --json state' "$GH_LOG" | tail -1 | cut -d: -f1)
judged_at=$(grep -n "^review of $new_head: success\$" "$GH_LOG" | head -1 | cut -d: -f1)
if released && grep -q "^review started on $new_head\$" "$out" && [ "$(grep -c '^workflow run sdlc-review-llm.yml' "$GH_LOG")" = 1 ] &&
  [ "${judged_at:-99999}" -lt "${merged_at:-0}" ]; then
  pass "release starts the review on a commit pushed to the release branch during the wait"
else
  fail "expected a review on the new head: status $status, $(cat "$out" "$err" "$GH_LOG")"
fi

release_case
printf '%s' "$new_head" >"$GH_HEAD.2"
printf '%s' "$new_head" >"$GH_HEAD"
printf failure >"$GH_REVIEW@$new_head"
release_run 60
if [ "$status" -ne 0 ] && grep -q '^STOPPED: the review of PR #5 ended failure' "$err" && ! merged_by_hand; then
  pass "release judges the review of the PR's new head commit, not the one it started with"
else
  fail "expected the new head's failed review to stop: status $status, $(cat "$out" "$err")"
fi

# A running review posts success and its run completes between the two reads of the first check.
release_case
printf pending >"$GH_REVIEW.1"
printf in_progress >"$GH_RUN.1"
printf success >"$GH_REVIEW"
printf completed >"$GH_RUN"
merges_on_read 3
GH_REVIEW_CLOCK="$work/gh-review-clock" release_run 60
if released && ! grep -q '^workflow run' "$GH_LOG"; then
  pass "release starts no second review when the running one finishes between its reads"
else
  fail "expected no dispatch for a review finishing mid-check: status $status, $(cat "$out" "$err" "$GH_LOG")"
fi

# An abandoned release attempt left origin/release/v0.1.1 in this clone, though its branch is gone from origin.
release_case
git update-ref refs/remotes/origin/release/v0.1.1 "$(git commit-tree 'HEAD^{tree}' -p HEAD -m abandoned)"
merges_on_read 3
release_run 60
if released && ! git --git-dir="$work/rel.git" log --format=%s main | grep -qx abandoned; then
  pass "release starts the branch from origin/main when the release branch was deleted from origin"
else
  fail "expected the stale origin/release/v0.1.1 to be ignored: status $status, $(cat "$out" "$err")"
fi

# A failed read of the review run must not pass for no run, which would start a second paid review.
release_case
printf pending >"$GH_REVIEW"
printf in_progress >"$GH_RUN"
printf '!fail' >"$GH_RUN.1"
merges_on_read 3
release_run 60
if released && ! grep -q '^workflow run' "$GH_LOG"; then
  pass "release starts no review when gh fails to read the review run"
else
  fail "expected no dispatch after a failed read: status $status, $(cat "$out" "$err" "$GH_LOG")"
fi

release_case
printf '!fail' >"$GH_REVIEW.1"
merges_on_read 3
release_run 60
if released && [ "$(grep -c '^workflow run sdlc-review-llm.yml' "$GH_LOG")" = 1 ]; then
  pass "release starts the review on a later poll when gh fails to read the review status"
else
  fail "expected one dispatch on a later poll: status $status, $(cat "$out" "$err" "$GH_LOG")"
fi

if [ "$failures" -ne 0 ]; then
  printf '%s check(s) failed\n' "$failures"
  exit 1
fi
printf 'All release script checks passed\n'
