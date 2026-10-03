#!/usr/bin/env bash
set -euo pipefail

# Ensure database schema is up to date before starting the API
python -m alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT"
