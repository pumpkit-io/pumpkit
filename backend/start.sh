#!/usr/bin/env bash
set -euo pipefail

# Ensure database schema is up to date before starting the API
python -m alembic upgrade head

# Trust X-Forwarded-For from Docker's private ranges, since the web container's address is not fixed.
# Only the compose network may reach this port: a direct caller can forge the header, as on the dev stack's published one.
export FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}"

exec uvicorn pumpkit.main:app --host 0.0.0.0 --port 8000
