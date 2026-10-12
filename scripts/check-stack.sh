#!/bin/sh
# Checks a running production stack over HTTP, the way a Self-hoster's browser sees it.
# Usage: sh scripts/check-stack.sh [BASE_URL] (default http://localhost:8080). Needs curl.
set -eu

base_url=${1:-http://localhost:8080}
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

# Usage: get PATH. Sets $code to the HTTP status (000 when nothing answers) and $body to the body file.
get() {
  body=$work/body
  : >"$body"
  code=$(curl -s -o "$body" -w '%{http_code}' --max-time 10 "$base_url$1") || true
}

get /api/v1/health
if [ "$code" = 200 ] && [ "$(tr -d ' \n' <"$body")" = '{"status":"ok"}' ]; then
  pass "/api/v1/health answers 200 {\"status\":\"ok\"}"
else
  fail "/api/v1/health: expected 200 {\"status\":\"ok\"}, got $code $(head -c 200 "$body")"
fi

# A built index.html loads hashed bundles from /assets/; the dev one loads /src/main.tsx.
for path in / /home; do
  get "$path"
  if [ "$code" = 200 ] && grep -q '<div id="root">' "$body" && grep -q 'src="/assets/' "$body"; then
    pass "$path serves the built app's HTML"
  else
    fail "$path: expected 200 with the built app's HTML, got $code $(head -c 200 "$body")"
  fi
done

get /api/v1/instance
if [ "$code" = 200 ] && grep -q '"app_name"' "$body"; then
  pass "/api/v1/instance answers on the same origin"
else
  fail "/api/v1/instance: expected 200 with app_name, got $code $(head -c 200 "$body")"
fi

if [ "$failures" -gt 0 ]; then
  printf '%s check(s) failed against %s\n' "$failures" "$base_url"
  exit 1
fi
printf 'Every check passed against %s\n' "$base_url"
