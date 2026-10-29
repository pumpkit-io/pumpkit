#!/bin/sh
# Prepares a release commit: moves the Unreleased entries of CHANGELOG.md under "## [VERSION] - DATE",
# leaving an empty Unreleased above, and sets PUMPKIT_VERSION in .env.example. docs/releasing.md has the whole flow.
# Usage: sh scripts/prepare-release.sh VERSION, from the repo root (VERSION as X.Y.Z, without the v).
# RELEASE_DATE (YYYY-MM-DD) overrides today's UTC date, for the tests.
set -eu

scripts_dir=$(cd "$(dirname "$0")" && pwd)

if [ $# -ne 1 ]; then
  echo "Usage: sh scripts/prepare-release.sh VERSION" >&2
  exit 2
fi
version=${1#v}
if ! printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "$1 is not X.Y.Z; a pre-release (vX.Y.Z-rc.N) needs no prepared commit, see docs/releasing.md" >&2
  exit 1
fi
date=${RELEASE_DATE:-$(date -u +%Y-%m-%d)}

for file in CHANGELOG.md .env.example; do
  if [ ! -f "$file" ]; then
    echo "$file not found: run this from the repo root" >&2
    exit 1
  fi
done
if ! grep -qx '## \[Unreleased\]' CHANGELOG.md; then
  echo 'CHANGELOG.md has no "## [Unreleased]" heading' >&2
  exit 1
fi
if grep -q "^## \[$version\]" CHANGELOG.md; then
  echo "CHANGELOG.md already has a section for $version" >&2
  exit 1
fi
if ! sh "$scripts_dir/release-notes.sh" Unreleased >/dev/null 2>&1; then
  echo "CHANGELOG.md's Unreleased section is empty: there is nothing to release" >&2
  exit 1
fi

# The newest released version is the first "## [X.Y.Z]" heading; the new one must be above it.
latest=$(sed -n 's/^## \[\([0-9][0-9.]*\)\].*/\1/p' CHANGELOG.md | head -1)
if [ -n "$latest" ]; then
  lowest=$(printf '%s\n%s\n' "$latest" "$version" | sort -t. -k1,1n -k2,2n -k3,3n | head -1)
  if [ "$lowest" = "$version" ]; then
    echo "$version is not above the latest release in CHANGELOG.md, $latest" >&2
    exit 1
  fi
fi

work=$(mktemp)
trap 'rm -f "$work"' EXIT
awk -v heading="## [$version] - $date" '
  $0 == "## [Unreleased]" { print; print ""; print heading; next }
  { print }
' CHANGELOG.md >"$work"
cat "$work" >CHANGELOG.md

sed "s/^PUMPKIT_VERSION=.*/PUMPKIT_VERSION=$version/" .env.example >"$work"
cat "$work" >.env.example

sh "$scripts_dir/release-notes.sh" "$version"
printf '\nPrepared %s: CHANGELOG.md has "## [%s] - %s" and .env.example sets PUMPKIT_VERSION=%s.\n' "$version" "$version" "$date" "$version"
