#!/usr/bin/env bash
# Startup script for Render (and any containerised environment).
# Runs Alembic migrations before the server starts — idempotent,
# so safe to re-run on every redeploy.
set -euo pipefail

echo "▶ running database migrations..."
alembic upgrade head

echo "▶ starting uvicorn on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
