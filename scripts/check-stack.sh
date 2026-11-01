#!/bin/sh
# Checks a running production stack over HTTP, the way a Self-hoster's browser sees it.
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
for path in / /new; do
  get "$path"
  if [ "$code" = 200 ] && is_app_html && grep -q 'src="/assets/' "$body"; then
    pass "$path serves the built app's HTML"
  else
    fail "$path: expected 200 with the built app's HTML, got $code $(head -c 200 "$body")"
  fi
done

get /
if [ "$code" = 200 ] && grep -q "<link rel=\"canonical\" href=\"$base_url/\"" "$body" &&
  ! grep -q '__PUBLIC_URL__' "$body"; then
  pass "/ names $base_url/ as its canonical URL"
else
  fail "/: expected the canonical URL $base_url/ and no __PUBLIC_URL__ placeholder"
fi
case "$base_url" in
  https://pumpkit.io) ;;
  *)
    if grep -q 'https://pumpkit\.io' "$body"; then
      fail "/: an Instance at $base_url still names https://pumpkit.io: $(grep -o 'https://pumpkit\.io[^"]*' "$body" | head -3 | tr '\n' ' ')"
    else
      pass "/ names no pumpkit.io URL"
    fi
    ;;
esac

# Set EXPECT_SEARCH_INDEXING=true to check an Instance with ALLOW_SEARCH_INDEXING=true.
if [ "${EXPECT_SEARCH_INDEXING:-false}" = true ]; then
  robots_meta='index,follow'
  robots_rule='Allow: /'
else
  robots_meta='noindex,nofollow'
  robots_rule='Disallow: /$'
fi
if grep -q "<meta name=\"robots\" content=\"$robots_meta\"" "$body"; then
  pass "/ carries the robots tag $robots_meta"
else
  fail "/: expected the robots tag $robots_meta, got $(grep -o '<meta name="robots"[^>]*>' "$body" || echo none)"
fi
get /robots.txt
if [ "$code" = 200 ] && grep -q "^$robots_rule" "$body"; then
  pass "/robots.txt says $robots_rule"
else
  fail "/robots.txt: expected 200 with '$robots_rule', got $code $(head -c 200 "$body")"
fi

get /api/v1/instance
if [ "$code" = 200 ] && grep -q '"app_name"' "$body"; then
  pass "/api/v1/instance answers on the same origin"
else
  fail "/api/v1/instance: expected 200 with app_name, got $code $(head -c 200 "$body")"
fi

get /.well-known/oauth-authorization-server
if [ "$code" = 200 ] && grep -q "\"issuer\":\"$base_url\"" "$body"; then
  pass "/.well-known/oauth-authorization-server reaches the backend with issuer $base_url"
else
  fail "/.well-known/oauth-authorization-server: expected the backend's JSON with issuer $base_url, got $code $(head -c 200 "$body"); forward /.well-known/oauth-* to the backend"
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
