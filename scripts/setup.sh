#!/bin/sh
# Writes the root .env for a Pumpkit Instance. POSIX sh; needs only openssl beyond the base system.
set -eu

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(dirname -- "$script_dir")
template=$repo_root/.env.example
env_file=$repo_root/.env

required="PUBLIC_URL LLM_API_KEY TWITTERAPI_IO_API_KEY"
generated="POSTGRES_PASSWORD JWT_SECRET_KEY FERNET_ENCRYPTION_KEY"

usage() {
  cat <<'EOF'
Usage: sh scripts/setup.sh [--env-file PATH] [--setting-name VALUE | --setting-name=VALUE ...]

Writes .env for a Pumpkit Instance. Values already in .env are kept as they are,
so running it again never rotates a secret or drops a key.

Required, as flags or environment variables of the same name:
  --public-url              PUBLIC_URL, the address Users open, like https://pumpkit.example.org
  --llm-api-key             LLM_API_KEY, for an OpenAI-compatible endpoint (OpenRouter by default)
  --twitterapi-io-api-key   TWITTERAPI_IO_API_KEY, from twitterapi.io

Generated when absent: POSTGRES_PASSWORD, JWT_SECRET_KEY, FERNET_ENCRYPTION_KEY.

Any other setting in .env.example is accepted the same way, for example
--stripe-secret-key or STRIPE_SECRET_KEY. Prefer environment variables for keys:
flags end up in your shell history.

Without a terminal on stdin, a missing required value fails the run and is named.
In a terminal, the script asks for it.

  --env-file PATH   write PATH instead of the repo's .env
  -h, --help        show this help
EOF
}

die() {
  printf 'setup.sh: %s\n' "$*" >&2
  exit 1
}

contains() {
  case " $1 " in
    *" $2 "*) return 0 ;;
  esac
  return 1
}

[ -f "$template" ] || die "$template not found; run this script from a Pumpkit checkout"
# Every setting .env.example names, set or commented out, is one this script accepts.
known=$(sed -n 's/^#\{0,1\} \{0,1\}\([A-Z][A-Z0-9_]*\)=.*/\1/p' "$template" | tr '\n' ' ')

set_flag() {
  name=$(printf '%s' "${1#--}" | tr 'a-z-' 'A-Z_')
  contains "$known" "$name" || die "unknown option $1 (see --help)"
  eval "flag_$name=\$2"
}

while [ $# -gt 0 ]; do
  case $1 in
    -h | --help)
      usage
      exit 0
      ;;
    --env-file=*)
      env_file=${1#*=}
      shift
      ;;
    --env-file)
      [ $# -ge 2 ] || die "--env-file needs a path"
      env_file=$2
      shift 2
      ;;
    --*=*)
      set_flag "${1%%=*}" "${1#*=}"
      shift
      ;;
    --*)
      [ $# -ge 2 ] || die "$1 needs a value"
      set_flag "$1" "$2"
      shift 2
      ;;
    *) die "unexpected argument $1 (see --help)" ;;
  esac
done

[ -d "$(dirname -- "$env_file")" ] || die "the folder for $env_file does not exist"

# A value counts as present only when it is not empty, so a bare NAME= line still gets filled.
existing_value() {
  [ -f "$env_file" ] || return 0
  value=$(sed -n "s/^$1=//p" "$env_file" | sed -n 1p)
  case $value in
    "''" | '""') value= ;;
  esac
  printf '%s' "$value"
}

# A flag wins over an environment variable of the same name.
passed_value() {
  eval "value=\${flag_$1-}"
  [ -n "$value" ] || eval "value=\${$1-}"
  printf '%s' "$value"
}

ask() {
  case $1 in
    PUBLIC_URL)
      printf 'PUBLIC_URL, the address Users open [http://localhost:8080]: ' >&2
      IFS= read -r answer || answer=
      [ -n "$answer" ] || answer=http://localhost:8080
      ;;
    *)
      case $1 in
        LLM_API_KEY) printf 'LLM_API_KEY, for an OpenAI-compatible endpoint (input hidden): ' >&2 ;;
        TWITTERAPI_IO_API_KEY) printf 'TWITTERAPI_IO_API_KEY, from twitterapi.io (input hidden): ' >&2 ;;
      esac
      trap 'stty echo' EXIT INT TERM
      stty -echo
      IFS= read -r answer || answer=
      stty echo
      trap - EXIT INT TERM
      printf '\n' >&2
      ;;
  esac
  printf '%s' "$answer"
}

generate() {
  command -v openssl >/dev/null 2>&1 || die "openssl is needed to generate $1; install it and run again"
  case $1 in
    FERNET_ENCRYPTION_KEY) openssl rand -base64 32 | tr '+/' '-_' ;;
    *) openssl rand -hex 32 ;;
  esac
}

# Single quotes keep a value literal for Docker Compose, python-dotenv and sh alike.
formatted() {
  case $1 in
    *[!A-Za-z0-9_./:@,+=-]*) printf "'%s'" "$1" ;;
    *) printf '%s' "$1" ;;
  esac
}

pending=
missing=
generated_now=
set_now=
kept=
for name in $known; do
  if [ -n "$(existing_value "$name")" ]; then
    [ -z "$(passed_value "$name")" ] || kept="$kept $name"
    continue
  fi
  value=$(passed_value "$name")
  if [ -z "$value" ] && contains "$generated" "$name"; then
    value=$(generate "$name")
    generated_now="$generated_now $name"
  elif [ -n "$value" ]; then
    set_now="$set_now $name"
  fi
  if [ -z "$value" ] && contains "$required" "$name" && [ -t 0 ]; then
    value=$(ask "$name")
    [ -z "$value" ] || set_now="$set_now $name"
  fi
  if [ -z "$value" ]; then
    if contains "$required" "$name"; then missing="$missing $name"; fi
    continue
  fi
  case $value in
    *"'"* | *'
'*) die "$name holds a single quote or a line break, which .env cannot carry" ;;
  esac
  eval "new_$name=\$value"
  pending="$pending $name"
done

if [ -n "$missing" ]; then
  {
    printf 'Missing required values:\n'
    for name in $missing; do
      flag=$(printf '%s' "$name" | tr 'A-Z_' 'a-z-')
      printf '  %s (pass --%s or set the %s environment variable)\n' "$name" "$flag" "$name"
    done
  } >&2
  exit 1
fi

# Fill each value on its NAME= or commented-out line, in place, and append the rest.
if [ -n "$pending" ]; then
  if [ -f "$env_file" ]; then source_file=$env_file; else source_file=$template; fi
  tmp=$env_file.tmp.$$
  umask 077
  trap 'rm -f "$tmp"' EXIT
  written=
  while IFS= read -r line || [ -n "$line" ]; do
    for name in $pending; do
      contains "$written" "$name" && continue
      case $line in
        "$name="* | "# $name="*)
          eval "value=\$new_$name"
          printf '%s=%s\n' "$name" "$(formatted "$value")"
          written="$written $name"
          continue 2
          ;;
      esac
    done
    printf '%s\n' "$line"
  done <"$source_file" >"$tmp"
  for name in $pending; do
    contains "$written" "$name" && continue
    eval "value=\$new_$name"
    printf '%s=%s\n' "$name" "$(formatted "$value")" >>"$tmp"
  done
  chmod 600 "$tmp"
  mv "$tmp" "$env_file"
  trap - EXIT
  printf 'Wrote %s (mode 600).\n' "$env_file"
else
  printf '%s already holds every required value; nothing changed.\n' "$env_file"
fi
chmod 600 "$env_file"

[ -z "$generated_now" ] || printf 'Generated:%s\n' "$generated_now"
[ -z "$set_now" ] || printf 'Set:%s\n' "$set_now"
[ -z "$kept" ] || printf 'Kept the value already in .env, ignoring the one passed:%s\n' "$kept"
printf 'Next, start Pumpkit:\n  docker compose up -d\n'
