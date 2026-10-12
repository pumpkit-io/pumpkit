#!/bin/sh
# Prints the body of one version's section of a Keep a Changelog file, for a GitHub Release's notes.
# Usage: sh scripts/release-notes.sh VERSION [CHANGELOG] (VERSION as in the heading, e.g. 0.1.0 or Unreleased).
# Exits 1 when the file has no "## [VERSION]" heading or the section under it is empty.
set -eu

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  echo "Usage: sh scripts/release-notes.sh VERSION [CHANGELOG]" >&2
  exit 2
fi
version=$1
changelog=${2:-CHANGELOG.md}

if [ ! -f "$changelog" ]; then
  echo "$changelog not found" >&2
  exit 1
fi

# Compares the bracketed text exactly, so 0.1.1 never matches 0.1.10. Trims blank lines at both ends.
notes=$(awk -v heading="## [$version]" '
  /^## / {
    if (found) exit
    if (substr($0, 1, length(heading)) == heading) {
      rest = substr($0, length(heading) + 1)
      if (rest == "" || rest ~ /^[ \t]/) found = 1
    }
    next
  }
  found {
    if ($0 ~ /^[ \t]*$/) { if (started) blanks++; next }
    for (; blanks > 0; blanks--) print ""
    started = 1
    print
  }
' "$changelog")

if [ -z "$notes" ]; then
  echo "$changelog has no entries for $version: add a \"## [$version]\" section (move the Unreleased entries under it) before tagging v$version" >&2
  exit 1
fi
printf '%s\n' "$notes"
