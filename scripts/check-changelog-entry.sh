#!/bin/sh
# Checks a PR records its change in CHANGELOG.md: new or changed entries under Unreleased, or, for a
# release PR from scripts/prepare-release.sh, a new version section. PRs labelled no-changelog skip it.
# Usage: sh scripts/check-changelog-entry.sh BASE, from the repo root (BASE: the commit the PR merges into).
set -eu

scripts_dir=$(cd "$(dirname "$0")" && pwd)

if [ $# -ne 1 ]; then
  echo "Usage: sh scripts/check-changelog-entry.sh BASE" >&2
  exit 2
fi
base=$1

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git show "$base:CHANGELOG.md" >"$work/base.md" 2>/dev/null || : >"$work/base.md"

versions() {
  sed -n 's/^## \[\([0-9][^]]*\)\].*/\1/p' "$1" | sort
}
versions "$work/base.md" >"$work/base-versions"
versions CHANGELOG.md >"$work/head-versions"
if [ -n "$(comm -13 "$work/base-versions" "$work/head-versions")" ]; then
  echo "ok: this PR adds a release section to CHANGELOG.md"
  exit 0
fi

sh "$scripts_dir/release-notes.sh" Unreleased "$work/base.md" >"$work/before" 2>/dev/null || true
sh "$scripts_dir/release-notes.sh" Unreleased CHANGELOG.md >"$work/after" 2>/dev/null || true
if [ -s "$work/after" ] && ! cmp -s "$work/before" "$work/after"; then
  echo "ok: this PR changes the Unreleased section of CHANGELOG.md"
  exit 0
fi

cat >&2 <<'EOF'
CHANGELOG.md has no entry for this PR. Either:
- add a line under "## [Unreleased]" saying what changes for Users or Self-hosters, under ### Added, Changed, Fixed, Removed or Security, with **Upgrade notes:** for any manual step an upgrade needs; or
- label the PR no-changelog when nobody running or using an Instance would notice (tests, refactors, CI, docs for contributors).
EOF
exit 1
