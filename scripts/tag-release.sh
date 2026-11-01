#!/bin/sh
# Tags origin/main as vVERSION after checking it is ready, pushes only the tag, then waits for the Release workflow.
# Usage: sh scripts/tag-release.sh VERSION, from any checkout of the repo (X.Y.Z, or X.Y.Z-rc.N for a dry run).
# RELEASE_WATCH=false skips waiting on GitHub, for the tests; RELEASE_POLL_SECONDS sets the pause between polls.
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

git fetch --quiet --tags origin
commit=$(git rev-parse --verify --quiet "origin/main^{commit}") || fail "origin/main not found; is origin the pumpkit repository?"

# Reads the files at that commit, so the checkout and its working tree never matter.
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
git show "$commit:.env.example" >"$work/env" 2>/dev/null || fail ".env.example not found at origin/main"
git show "$commit:CHANGELOG.md" >"$work/changelog" 2>/dev/null || fail "CHANGELOG.md not found at origin/main"

# The Release workflow checks the same two things; failing here keeps a bad tag off GitHub.
expected=${version%%-*}
actual=$(sed -n 's/^PUMPKIT_VERSION=//p' "$work/env")
[ "$actual" = "$expected" ] ||
  fail "origin/main sets PUMPKIT_VERSION=$actual in .env.example, not $expected: merge the PR from scripts/prepare-release.sh $expected first"
case $version in
  *-*) sh "$scripts_dir/release-notes.sh" "$version" "$work/changelog" >/dev/null 2>&1 ||
    sh "$scripts_dir/release-notes.sh" Unreleased "$work/changelog" >/dev/null ||
    fail "CHANGELOG.md has entries neither for $version nor under Unreleased" ;;
  *) sh "$scripts_dir/release-notes.sh" "$version" "$work/changelog" >/dev/null ||
    fail "merge the PR from scripts/prepare-release.sh $version first" ;;
esac

if git rev-parse --quiet --verify "refs/tags/$tag" >/dev/null ||
  [ -n "$(git ls-remote --tags origin "refs/tags/$tag")" ]; then
  fail "the tag $tag already exists; a released version is never re-tagged, so release the next version instead"
fi

git tag -a "$tag" -m "$tag" "$commit"
git push --quiet origin "refs/tags/$tag"
printf 'Pushed %s at %s.\n' "$tag" "$(git rev-parse --short "$commit")"

if [ "${RELEASE_WATCH:-true}" = false ]; then
  exit 0
fi

poll=${RELEASE_POLL_SECONDS:-2}
# The run appears a few seconds after the push; a tag push runs with the tag as its branch.
run=
attempt=0
while [ -z "$run" ] && [ "$attempt" -lt 30 ]; do
  sleep "$poll"
  run=$(gh run list --workflow release.yml --branch "$tag" --limit 1 --json databaseId -q '.[0].databaseId')
  attempt=$((attempt + 1))
done
[ -n "$run" ] || fail "no Release workflow run started for $tag within a minute; check https://github.com/pumpkit-io/pumpkit/actions"
# A dropped connection makes gh run watch exit non-zero for a run that goes on; only the run's conclusion says it failed.
attempt=0
conclusion=
while [ "$attempt" -lt 5 ]; do
  if gh run watch "$run" --exit-status >/dev/null; then
    conclusion=success
    break
  fi
  conclusion=$(gh run view "$run" --json conclusion -q .conclusion 2>/dev/null || true)
  case $conclusion in
    success | failure | cancelled) break ;;
  esac
  conclusion=
  attempt=$((attempt + 1))
  sleep "$poll"
done
case $conclusion in
  success) ;;
  failure | cancelled) fail "the Release workflow ended $conclusion for $tag: read it with gh run view $run --log-failed" ;;
  *) fail "the watch lost its connection before the Release workflow for $tag finished: $(gh run view "$run" --json url -q .url 2>/dev/null || echo "https://github.com/pumpkit-io/pumpkit/actions/runs/$run")" ;;
esac
gh release view "$tag"
