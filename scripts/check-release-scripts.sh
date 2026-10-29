#!/bin/sh
# Checks prepare-release.sh, tag-release.sh and check-changelog-entry.sh against throwaway git repos.
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
git checkout -q -b other
run sh "$scripts/tag-release.sh" 0.2.0
if [ "$status" -ne 0 ] && grep -q 'main' "$err"; then
  pass "tag-release refuses a branch other than main"
else
  fail "expected tag-release to refuse branch other, got status $status"
fi
git checkout -q main

echo dirty >>CHANGELOG.md
run sh "$scripts/tag-release.sh" 0.2.0
if [ "$status" -ne 0 ] && grep -q 'changes' "$err"; then
  pass "tag-release refuses a working tree with changes"
else
  fail "expected tag-release to refuse a dirty tree, got status $status"
fi
git checkout -q -- .

run sh "$scripts/tag-release.sh" 0.3.0
if [ "$status" -ne 0 ] && grep -q 'PUMPKIT_VERSION=0.2.0' "$err"; then
  pass "tag-release refuses a version .env.example doesn't set"
else
  fail "expected tag-release to refuse 0.3.0, got status $status"
fi

git commit -q --allow-empty -m "not pushed"
run sh "$scripts/tag-release.sh" 0.2.0
if [ "$status" -ne 0 ] && grep -q 'origin/main' "$err"; then
  pass "tag-release refuses a main that isn't level with origin/main"
else
  fail "expected tag-release to refuse an unpushed main, got status $status"
fi
git reset -q --hard origin/main

run sh "$scripts/tag-release.sh" 0.2.0
if [ "$status" -eq 0 ] && [ "$(git --git-dir="$work/prep.git" tag)" = v0.2.0 ] &&
  [ "$(git --git-dir="$work/prep.git" cat-file -t v0.2.0)" = tag ]; then
  pass "tag-release pushes an annotated tag"
else
  fail "expected tag-release to push v0.2.0: status $status, $(cat "$err")"
fi

run sh "$scripts/tag-release.sh" 0.2.0
if [ "$status" -ne 0 ] && grep -q 'already exists' "$err"; then
  pass "tag-release refuses a tag that exists"
else
  fail "expected tag-release to refuse an existing tag, got status $status"
fi

if [ "$failures" -ne 0 ]; then
  printf '%s check(s) failed\n' "$failures"
  exit 1
fi
printf 'All release script checks passed\n'
