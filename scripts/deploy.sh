#!/usr/bin/env bash
# Usage: bash scripts/deploy.sh (reads ./deploy.env; see deploy.env.example)
# One-time server provisioning: docs/deployment.md

set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

if [[ ! -f deploy.env ]]; then
  echo "✗ deploy.env not found. Copy deploy.env.example to deploy.env and fill it in." >&2
  exit 1
fi
# shellcheck disable=SC1091
source deploy.env

for v in PUBLIC_URL DOMAIN ACME_EMAIL SSH_HOST BRANCH APP_USER APP_DIR SERVICE_NAME; do
  if [[ -z "${!v:-}" ]]; then
    echo "✗ $v is not set in deploy.env" >&2
    exit 1
  fi
done

if [[ -t 1 ]]; then
  c_blue='\033[1;36m'; c_green='\033[1;32m'; c_yellow='\033[1;33m'; c_red='\033[1;31m'; c_reset='\033[0m'
else
  c_blue=''; c_green=''; c_yellow=''; c_red=''; c_reset=''
fi
log()  { printf "${c_blue}▶${c_reset} %s\n" "$*"; }
ok()   { printf "${c_green}✓${c_reset} %s\n" "$*"; }
warn() { printf "${c_yellow}⚠${c_reset} %s\n" "$*"; }
err()  { printf "${c_red}✗${c_reset} %s\n" "$*" >&2; }

confirm() {
  local yn
  read -rp "$1 [y/N] " yn
  [[ "$yn" =~ ^[Yy]$ ]]
}

log "Local sanity checks"

if ! git diff --quiet HEAD --; then
  warn "Working tree has uncommitted changes — these will NOT be deployed."
  git status --short
  confirm "Continue anyway?" || { err "Aborted"; exit 1; }
fi

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
  warn "On '$CURRENT_BRANCH', not '$BRANCH'. The server always pulls origin/$BRANCH."
  confirm "Continue anyway?" || { err "Aborted"; exit 1; }
fi

git fetch --quiet origin "$BRANCH"
AHEAD=$(git rev-list --count "origin/$BRANCH..HEAD")
if (( AHEAD > 0 )); then
  warn "$AHEAD local commit(s) ahead of origin/$BRANCH — push first to deploy them:"
  git log "origin/$BRANCH..HEAD" --oneline
  confirm "Continue anyway?" || { err "Aborted"; exit 1; }
fi

ORIGIN_SHA=$(git rev-parse --short "origin/$BRANCH")
ok "Local: $(git rev-parse --short HEAD) · origin/$BRANCH: $ORIGIN_SHA"

log "Verifying SSH access to $SSH_HOST"
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$SSH_HOST" true 2>/dev/null; then
  err "Cannot SSH to $SSH_HOST. Check ~/.ssh/config."
  exit 1
fi
ok "SSH OK"

log "Updating server"
ssh "$SSH_HOST" \
  "APP_USER='$APP_USER' APP_DIR='$APP_DIR' SERVICE_NAME='$SERVICE_NAME' BRANCH='$BRANCH' DOMAIN='$DOMAIN' ACME_EMAIL='$ACME_EMAIL' bash -s" <<'REMOTE'
set -euo pipefail

echo "▶ Ensuring $APP_DIR is owned by $APP_USER"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "▶ Pulling latest origin/$BRANCH"
sudo -u "$APP_USER" bash -lc "set -e; cd '$APP_DIR'; git fetch origin; git reset --hard 'origin/$BRANCH'; echo \"   deployed SHA: \$(git rev-parse --short HEAD)\""

echo "▶ Syncing Caddyfile ($APP_DIR/infra/Caddyfile -> /etc/caddy/Caddyfile)"
if diff -q "$APP_DIR/infra/Caddyfile" /etc/caddy/Caddyfile > /dev/null 2>&1; then
  echo "   ✓ Caddyfile unchanged"
else
  echo "   → validating new Caddyfile"
  env DOMAIN="$DOMAIN" ACME_EMAIL="$ACME_EMAIL" APP_DIR="$APP_DIR" \
    caddy validate --config "$APP_DIR/infra/Caddyfile" --adapter caddyfile
  ts=$(date +%Y%m%d-%H%M%S)
  cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.${ts}.bak" 2>/dev/null || true
  cp "$APP_DIR/infra/Caddyfile" /etc/caddy/Caddyfile
  systemctl reload caddy
  echo "   ✓ Caddyfile updated and reloaded (backup: /etc/caddy/Caddyfile.${ts}.bak)"
fi

echo "▶ Syncing Python deps (uv sync)"
sudo -u "$APP_USER" bash -lc "set -e; cd '$APP_DIR/backend'; ~/.local/bin/uv sync"

echo "▶ Building frontend (env vars from $APP_DIR/frontend/.env)"
sudo -u "$APP_USER" bash -lc "
  set -e
  cd '$APP_DIR/frontend'
  # vite compiles with undefined env vars and ships a broken bundle; fail fast.
  grep -qE '^VITE_API_URL=.' .env 2>/dev/null || { echo '✗ missing or empty VITE_API_URL in frontend/.env'; exit 1; }
  rm -rf dist
  npm ci --no-progress --no-audit --no-fund
  npm run build
"

echo "▶ Restarting $SERVICE_NAME (alembic runs via ExecStartPre)"
systemctl restart "$SERVICE_NAME"

echo "▶ Waiting for backend to bind 127.0.0.1:8000 (up to 60s)"
for _ in $(seq 1 30); do
  ss -lntp 2>/dev/null | grep -q ":8000\b" && break
  sleep 2
done
if ! ss -lntp 2>/dev/null | grep -q ":8000\b"; then
  echo "✗ Backend did not bind port 8000"
  journalctl -u "$SERVICE_NAME" --no-pager -n 40
  exit 1
fi
systemctl is-active --quiet "$SERVICE_NAME" || { echo "✗ $SERVICE_NAME is not active"; exit 1; }
echo "✓ Backend active and listening on 8000"
REMOTE

log "Public smoke test"
spa_code=$(curl -sS -o /dev/null -w "%{http_code}" "$PUBLIC_URL/" || echo 000)
api_code=$(curl -sS -o /dev/null -w "%{http_code}" "$PUBLIC_URL/api/v1/users/me" || echo 000)
if [[ "$spa_code" == "200" && "$api_code" == "401" ]]; then
  ok "$PUBLIC_URL/ → $spa_code (SPA)"
  ok "$PUBLIC_URL/api/v1/users/me → $api_code (auth required)"
else
  err "Smoke test failed — SPA=$spa_code, API=$api_code"
  err "Inspect logs: ssh $SSH_HOST 'journalctl -u $SERVICE_NAME -n 40'"
  exit 1
fi

# Optional PostHog release annotation (soft-fails).
if [[ -n "${POSTHOG_PROJECT_ID:-}" ]]; then
  if [[ -z "${POSTHOG_PERSONAL_API_KEY:-}" && -f backend/.env ]]; then
    POSTHOG_PERSONAL_API_KEY=$(grep -E '^POSTHOG_PERSONAL_API_KEY=' backend/.env | head -1 | cut -d= -f2-)
  fi
  if [[ -n "${POSTHOG_PERSONAL_API_KEY:-}" ]]; then
    log "Creating PostHog release annotation"
    status=$(curl -sS -o /dev/null -w "%{http_code}" \
      -X POST "${POSTHOG_API_HOST:-https://eu.posthog.com}/api/projects/$POSTHOG_PROJECT_ID/annotations/" \
      -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" -H "Content-Type: application/json" \
      -d "{\"content\":\"Deploy $ORIGIN_SHA\",\"scope\":\"project\",\"date_marker\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" || echo "000")
    [[ "$status" == "201" ]] && ok "Annotated PostHog with deploy $ORIGIN_SHA" || warn "PostHog annotation failed (HTTP $status)"
  else
    warn "POSTHOG_PERSONAL_API_KEY not set — skipping PostHog annotation"
  fi
fi

ok "Deploy complete · live SHA: $ORIGIN_SHA"
