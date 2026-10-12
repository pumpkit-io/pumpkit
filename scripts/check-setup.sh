#!/bin/sh
# Checks scripts/setup.sh from outside, the way a Self-hoster or their agent runs it.
# Usage: sh scripts/check-setup.sh (needs uv for the backend check). SETUP_SHELL picks the shell.
set -eu

repo_root=$(cd "$(dirname "$0")/.." && pwd)
shell=${SETUP_SHELL:-sh}
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

llm_key=sk-or-check-llm-key-7f3a
twitter_key=check-twitterapi-key-91c2

# Usage: run_setup [NAME=value ...] [-- flag ...]. Runs setup.sh on $env_file without a terminal,
# in an environment holding only PATH and the assignments; sets $out and $status.
run_setup() {
  assignments=
  while [ $# -gt 0 ] && [ "$1" != -- ]; do
    assignments="$assignments $1"
    shift
  done
  [ $# -gt 0 ] && shift
  set +e
  # shellcheck disable=SC2086 # The assignments hold no spaces, so splitting them is intended.
  env -i PATH="$PATH" $assignments "$shell" "$repo_root/scripts/setup.sh" --env-file "$env_file" "$@" \
    </dev/null >"$out" 2>&1
  status=$?
  set -e
}

value_of() {
  sed -n "s/^$1=//p" "$env_file" | head -n 1
}

env_file=$work/first/.env
out=$work/first.out
mkdir -p "$work/first"
run_setup PUBLIC_URL=http://localhost:8080 LLM_API_KEY=$llm_key -- --twitterapi-io-api-key "$twitter_key"

if [ "$status" -eq 0 ] && [ -f "$env_file" ]; then
  pass "writes .env when every required value is passed"
else
  fail "expected exit 0 and a .env, got status $status:"
  cat "$out"
fi

if [ "$(ls -l "$env_file" | cut -c1-10)" = "-rw-------" ]; then
  pass "writes .env with mode 600"
else
  fail "expected mode 600, got $(ls -l "$env_file" | cut -c1-10)"
fi

for name in PUBLIC_URL POSTGRES_PASSWORD JWT_SECRET_KEY FERNET_ENCRYPTION_KEY LLM_API_KEY TWITTERAPI_IO_API_KEY; do
  [ -n "$(value_of "$name")" ] || fail "$name is empty in the written .env"
done
[ "$(value_of LLM_API_KEY)" = "$llm_key" ] || fail "LLM_API_KEY is not the passed key"
[ "$(value_of TWITTERAPI_IO_API_KEY)" = "$twitter_key" ] || fail "TWITTERAPI_IO_API_KEY is not the passed key"
pass "fills every required value"

# Every output must leave out each secret and key the .env holds.
check_output_hides_secrets() {
  for name in POSTGRES_PASSWORD JWT_SECRET_KEY FERNET_ENCRYPTION_KEY LLM_API_KEY TWITTERAPI_IO_API_KEY; do
    secret=$(value_of "$name")
    if grep -F -q -e "$secret" "$out"; then
      fail "$1: the output shows $name"
    fi
  done
}
check_output_hides_secrets "first run"

cp "$env_file" "$work/first.env"
out=$work/second.out
run_setup PUBLIC_URL=http://localhost:8080 LLM_API_KEY=$llm_key -- --twitterapi-io-api-key "$twitter_key"
if [ "$status" -eq 0 ] && cmp -s "$env_file" "$work/first.env"; then
  pass "a second run keeps .env byte for byte"
else
  fail "a second run changed .env or failed (status $status)"
  cat "$out"
fi
check_output_hides_secrets "second run"

out=$work/third.out
run_setup LLM_API_KEY=sk-or-another-key-0b1d -- --public-url https://pumpkit.example.org
if [ "$status" -eq 0 ] && cmp -s "$env_file" "$work/first.env"; then
  pass "a run passing other values keeps every existing one"
else
  fail "a run passing other values changed .env or failed (status $status)"
  cat "$out"
fi
if grep -F -q sk-or-another-key-0b1d "$out"; then
  fail "the output shows a passed key it ignored"
fi

env_file=$work/missing/.env
out=$work/missing.out
mkdir -p "$work/missing"
run_setup PUBLIC_URL=http://localhost:8080 TWITTERAPI_IO_API_KEY=$twitter_key
if [ "$status" -ne 0 ] && grep -q LLM_API_KEY "$out" && [ ! -e "$env_file" ]; then
  pass "without a terminal and LLM_API_KEY, fails naming LLM_API_KEY and writes nothing"
else
  fail "expected a non-zero exit naming LLM_API_KEY and no .env, got status $status:"
  cat "$out"
fi
if grep -F -q "$twitter_key" "$out"; then
  fail "the failing run shows TWITTERAPI_IO_API_KEY"
fi

env_file=$work/providers/.env
out=$work/providers.out
mkdir -p "$work/providers"
run_setup PUBLIC_URL=http://localhost:8080 LLM_API_KEY=$llm_key TWITTERAPI_IO_API_KEY=$twitter_key \
  STRIPE_SECRET_KEY=sk_test_dummy STRIPE_PUBLISHABLE_KEY=pk_test_dummy \
  'BILLING_PLAN_KEYS=["pumpkit_pro_monthly"]' -- --stripe-webhook-secret whsec_dummy
if [ "$status" -eq 0 ] && [ "$(value_of STRIPE_WEBHOOK_SECRET)" = whsec_dummy ]; then
  pass "accepts optional provider values"
else
  fail "expected optional provider values in .env, got status $status:"
  cat "$out"
fi
check_output_hides_secrets "run with providers"

# The backend builds its Fernet cipher and the rest of its settings on import, as at startup.
if (
  cd "$repo_root/backend"
  set -a
  # shellcheck disable=SC1090
  . "$env_file"
  set +a
  uv run --quiet python -c '
import pumpkit.main  # noqa: F401
from pumpkit.core import security
from pumpkit.core.config import settings

assert security.decrypt(security.encrypt("check")) == "check"
assert settings.BILLING_PLAN_KEYS == ["pumpkit_pro_monthly"], settings.BILLING_PLAN_KEYS
assert settings.is_stripe_billing_configured()
'
) >"$work/backend.out" 2>&1; then
  pass "the backend starts with the written .env and accepts its Fernet key"
else
  fail "the backend rejected the written .env:"
  cat "$work/backend.out"
fi

if [ "$failures" -ne 0 ]; then
  printf '%s check(s) failed\n' "$failures"
  exit 1
fi
printf 'All setup script checks passed\n'
