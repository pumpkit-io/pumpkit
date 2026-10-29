#!/bin/sh
# Tags main as vVERSION after checking it is ready, pushes only the tag, then waits for the Release workflow.
# Usage: sh scripts/tag-release.sh VERSION, from the repo root (X.Y.Z, or X.Y.Z-rc.N for a dry run).
# RELEASE_WATCH=false skips waiting on GitHub, for the tests.
set -eu

scripts_dir=$(cd "$(dirname "$0")" && pwd)

fail() {
  printf '%s\n' "$*" >&2
  exit 1
}

if [ $# -ne 1 ]; then
  echo "Usage: sh scripts/tag-release.sh VERSION" >&2
  exit 2
fi
version=${1#v}
printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$' ||
  fail "$1 is not X.Y.Z or X.Y.Z-rc.N"
tag=v$version

[ "$(git symbolic-ref --quiet --short HEAD || true)" = main ] ||
  fail "check out main first (git checkout main && git pull)"
# Untracked files never reach the tag, so only changes to tracked files stop it.
[ -z "$(git status --porcelain --untracked-files=no)" ] ||
  fail "the working tree has changes to tracked files; commit or discard them first"
git fetch --quiet --tags origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] ||
  fail "main is not level with origin/main; run git pull, and merge the release PR first"

# The Release workflow checks the same two things; failing here keeps a bad tag off GitHub.
expected=${version%%-*}
actual=$(sed -n 's/^PUMPKIT_VERSION=//p' .env.example)
[ "$actual" = "$expected" ] ||
  fail ".env.example sets PUMPKIT_VERSION=$actual, not $expected: merge the PR from scripts/prepare-release.sh $expected first"
case $version in
  *-*) sh "$scripts_dir/release-notes.sh" "$version" >/dev/null 2>&1 ||
    sh "$scripts_dir/release-notes.sh" Unreleased >/dev/null ||
    fail "CHANGELOG.md has entries neither for $version nor under Unreleased" ;;
  *) sh "$scripts_dir/release-notes.sh" "$version" >/dev/null ||
    fail "merge the PR from scripts/prepare-release.sh $version first" ;;
esac

if git rev-parse --quiet --verify "refs/tags/$tag" >/dev/null ||
  [ -n "$(git ls-remote --tags origin "refs/tags/$tag")" ]; then
  fail "the tag $tag already exists; a released version is never re-tagged, so release the next version instead"
fi

git tag -a "$tag" -m "$tag"
git push --quiet origin "refs/tags/$tag"
printf 'Pushed %s at %s.\n' "$tag" "$(git rev-parse --short HEAD)"

if [ "${RELEASE_WATCH:-true}" = false ]; then
  exit 0
fi

# The run appears a few seconds after the push; a tag push runs with the tag as its branch.
run=
attempt=0
while [ -z "$run" ] && [ "$attempt" -lt 30 ]; do
  sleep 2
  run=$(gh run list --workflow release.yml --branch "$tag" --limit 1 --json databaseId -q '.[0].databaseId')
  attempt=$((attempt + 1))
done
[ -n "$run" ] || fail "no Release workflow run started for $tag within a minute; check https://github.com/pumpkit-io/pumpkit/actions"
gh run watch "$run" --exit-status ||
  fail "the Release workflow failed for $tag: read it with gh run view $run --log-failed"
gh release view "$tag"
