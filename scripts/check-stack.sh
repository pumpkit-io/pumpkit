#!/bin/sh
# Checks a running production stack over HTTP, the way a Self-hoster's browser sees it.
# Usage: sh scripts/check-stack.sh [BASE_URL] (default http://localhost:8080). Needs curl.
# With POSTHOG_RELAY=true it expects the PostHog relay, which needs PostHog reachable from the stack.
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

# Usage: get PATH. Sets $code to the HTTP status (000 when nothing answers), $content_type,
# and $body to the body file.
get() {
  body=$work/body
  : >"$body"
  response=$(curl -s -o "$body" -w '%{http_code} %{content_type}' --max-time 10 "$base_url$1") || true
  code=${response%% *}
  content_type=${response#* }
}

is_app_html() {
  grep -q '<div id="root">' "$body"
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
  if [ "$code" = 200 ] && is_app_html && grep -q 'src="/assets/' "$body"; then
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

if [ "${POSTHOG_RELAY:-false}" = true ]; then
  get /ph-relay/static/array.js
  if [ "$code" = 200 ] && case $content_type in *javascript*) true ;; *) false ;; esac; then
    pass "/ph-relay/static/* proxies to PostHog's asset host"
  else
    fail "/ph-relay/static/array.js: expected 200 JavaScript from PostHog, got $code $content_type"
  fi

  get '/ph-relay/flags/?v=2'
  if [ "$code" = 200 ] && case $content_type in application/json*) true ;; *) false ;; esac; then
    pass "/ph-relay/* proxies to PostHog's ingestion host"
  else
    fail "/ph-relay/flags/: expected 200 JSON from PostHog, got $code $content_type"
  fi
else
  # By default the relay is off, so /ph-relay paths are just client routes.
  for path in /ph-relay/static/array.js '/ph-relay/flags/?v=2'; do
    get "$path"
    if [ "$code" = 200 ] && is_app_html; then
      pass "$path is not proxied to PostHog"
    else
      fail "$path: expected the app's HTML (relay off), got $code $content_type"
    fi
  done
fi

if [ "$failures" -gt 0 ]; then
  printf '%s check(s) failed against %s\n' "$failures" "$base_url"
  exit 1
fi
printf 'Every check passed against %s\n' "$base_url"
