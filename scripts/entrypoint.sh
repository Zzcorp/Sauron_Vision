#!/bin/sh
# Phase-30 production entrypoint.
# Runs migrations + collectstatic, then handoffs to the container CMD.
# Idempotent — safe to run on every container start.

set -eu

echo "[entrypoint] $(date -u +%FT%TZ) starting"

# Wait for DB to be reachable. Compose healthcheck handles this normally
# but in raw `docker run` we still need a guard.
WAITS=0
until python -c "import psycopg2, os; \
psycopg2.connect(host=os.environ.get('DB_HOST','db'), \
port=os.environ.get('DB_PORT','5432'), \
dbname=os.environ.get('DB_NAME','sauron_vision'), \
user=os.environ.get('DB_USER','sauron'), \
password=os.environ.get('DB_PASSWORD',''))" 2>/dev/null; do
    WAITS=$((WAITS + 1))
    if [ "$WAITS" -gt 30 ]; then
        echo "[entrypoint] DB never came up; failing." >&2
        exit 1
    fi
    echo "[entrypoint] waiting for DB ($WAITS/30)..."
    sleep 2
done

echo "[entrypoint] running migrations"
python manage.py migrate --noinput

echo "[entrypoint] collecting static files"
python manage.py collectstatic --noinput --clear 2>/dev/null \
    || python manage.py collectstatic --noinput

echo "[entrypoint] handoff to: $*"
exec "$@"
