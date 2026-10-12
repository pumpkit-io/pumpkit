#!/bin/sh
# Checks scripts/release-notes.sh, which the release workflow runs to turn a CHANGELOG section into release notes.
# Usage: sh scripts/check-release-notes.sh
set -eu

repo_root=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

failures=0
fail() {
  printf 'FAIL: %s\n' "$*"
  failures=$((failures + 1))
}
pass() {
  printf 'ok: %s\n' "$*"
}

# Usage: run_notes VERSION CHANGELOG. Sets $status, with stdout in $out and stderr in $err.
out=$work/out
err=$work/err
run_notes() {
  set +e
  sh "$repo_root/scripts/release-notes.sh" "$1" "$2" >"$out" 2>"$err"
  status=$?
  set -e
}

changelog=$work/CHANGELOG.md
cat >"$changelog" <<'EOF'
# Changelog

Before 1.0, upgrades may need manual steps.

## [Unreleased]

- Something not released yet.

## [0.1.10] - 2026-12-01

- Ten.

## [0.1.1] - 2026-11-01

### Changed

- One, first line.
- One, second line.

## [0.1.0] - 2026-10-20

## [0.0.9] - 2026-09-01

- Nine.
EOF

cat >"$work/expected-0.1.1" <<'EOF'
### Changed

- One, first line.
- One, second line.
EOF

run_notes 0.1.1 "$changelog"
if [ "$status" -eq 0 ] && cmp -s "$out" "$work/expected-0.1.1"; then
  pass "prints a version's section without its heading or the next section"
else
  fail "expected 0.1.1's section and exit 0, got status $status and:"
  cat "$out" "$err"
fi

run_notes 0.9.9 "$changelog"
if [ "$status" -ne 0 ] && [ ! -s "$out" ] && grep -q '0\.9\.9' "$err"; then
  pass "fails naming a version with no section"
else
  fail "expected a non-zero exit naming 0.9.9 and no notes, got status $status and:"
  cat "$out" "$err"
fi

run_notes 0.1.0 "$changelog"
if [ "$status" -ne 0 ] && [ ! -s "$out" ] && grep -q '0\.1\.0' "$err"; then
  pass "fails on a version whose section is empty"
else
  fail "expected a non-zero exit naming 0.1.0 and no notes, got status $status and:"
  cat "$out" "$err"
fi

run_notes 0.1.1 "$work/missing.md"
if [ "$status" -ne 0 ] && [ ! -s "$out" ]; then
  pass "fails when the changelog file is missing"
else
  fail "expected a non-zero exit for a missing file, got status $status"
fi

run_notes Unreleased "$repo_root/CHANGELOG.md"
if [ "$status" -eq 0 ] && [ -s "$out" ]; then
  pass "CHANGELOG.md has an Unreleased section with entries"
else
  fail "expected CHANGELOG.md to have a non-empty Unreleased section, got status $status:"
  cat "$err"
fi

if grep -q 'Before 1\.0' "$repo_root/CHANGELOG.md"; then
  pass "CHANGELOG.md carries the pre-1.0 note"
else
  fail "expected CHANGELOG.md to say that before 1.0 upgrades may need manual steps"
fi

if [ "$failures" -ne 0 ]; then
  printf '%s check(s) failed\n' "$failures"
  exit 1
fi
printf 'All release notes checks passed\n'
