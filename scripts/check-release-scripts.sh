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

if [ "$failures" -ne 0 ]; then
  printf '%s check(s) failed\n' "$failures"
  exit 1
fi
printf 'All release script checks passed\n'
