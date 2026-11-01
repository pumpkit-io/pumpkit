#!/bin/sh
# Prints the body of one version's section of a Keep a Changelog file, for a GitHub Release's notes.
# Usage: sh scripts/release-notes.sh VERSION [CHANGELOG] (VERSION as in the heading, e.g. 0.1.0 or Unreleased).
# Exits 1 when the file has no "## [VERSION]" heading or the section under it is empty.
#
# Usage: sh scripts/release-notes.sh --manual-steps VERSION|FROM..TO [CHANGELOG]
# Prints only the entries that carry **Upgrade notes:**, the ones an upgrade needs a manual step for, and nothing when
# there are none. FROM..TO covers the releases after FROM up to and including TO, each entry under its version heading.
# Exits 1 when a named version has no "## [VERSION]" heading.
set -eu

manual=false
if [ "${1:-}" = "--manual-steps" ]; then
  manual=true
  shift
fi

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  echo "Usage: sh scripts/release-notes.sh [--manual-steps] VERSION [CHANGELOG]" >&2
  exit 2
fi
version=$1
changelog=${2:-CHANGELOG.md}

if [ ! -f "$changelog" ]; then
  echo "$changelog not found" >&2
  exit 1
fi

if [ "$manual" = true ]; then
  case $version in
    *..*) from=${version%%..*} to=${version#*..} ;;
    *) from= to=$version ;;
  esac
  # Newest first, as the file lists them; a release is wanted when it sits at or after TO and before FROM.
  wanted=$(sed -n 's/^## \[\([0-9][^]]*\)\].*/\1/p' "$changelog" | awk -v from="$from" -v to="$to" '
    $0 == to { seen_to = 1 }
    from != "" && $0 == from { seen_from = 1; exit }
    seen_to { print; if (from == "") exit }
    END { if (!seen_to || (from != "" && !seen_from)) exit 1 }
  ') || {
    echo "$changelog has no \"## [$to]\"${from:+ or no \"## [$from]\" before it}: check the versions named" >&2
    exit 1
  }
  # An entry is a "- " line plus the indented lines after it.
  printf '%s\n' "$wanted" | awk -v multi="$([ -n "$from" ] && echo 1 || echo 0)" '
    function flush() {
      if (entry ~ /\*\*Upgrade notes:\*\*/) {
        if (multi && !shown) { if (printed) print ""; print "## [" version "]"; shown = 1 }
        print entry
        printed = 1
      }
      entry = ""
    }
    NR == FNR { want[$0] = 1; next }
    /^## / { flush(); version = $0; sub(/^## \[/, "", version); sub(/\].*/, "", version); inwant = (version in want); shown = 0; next }
    !inwant { next }
    /^- / { flush(); entry = $0; next }
    /^[ \t]+[^ \t]/ && entry != "" { entry = entry "\n" $0; next }
    { flush() }
    END { flush() }
  ' - "$changelog"
  exit 0
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
