#!/usr/bin/env bash
set -euo pipefail

# Ensure database schema is up to date before starting the API
python -m alembic upgrade head

# The web container sits on the compose network, whose address is not fixed, so trust the private
# ranges Docker allocates from. Without this uvicorn drops X-Forwarded-For and every per-IP rate
# limit sees Caddy's address. Only the web container reaches the backend's port, so a public caller
# cannot forge the header. Set FORWARDED_ALLOW_IPS in .env to narrow it.
export FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}"

exec uvicorn pumpkit.main:app --host 0.0.0.0 --port 8000
