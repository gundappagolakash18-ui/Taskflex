#!/bin/sh
set -e

echo "==> Running database migrations"
alembic upgrade head

if [ "$SEED_ON_START" = "true" ]; then
    echo "==> Seeding demo data (only if database is empty)"
    python -c "from app.db.seed_runner import seed_if_empty; seed_if_empty()"
fi

echo "==> Starting TASKFLEX API on port ${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
