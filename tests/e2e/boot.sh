#!/bin/bash
# E2E boot: migrate, seed (incl. --e2e org), serve, wait readiness, smoke.
# Full SPEC-frontend §5 (compose db+redis+mailpit, worker/beat, frontend
# preview) activates service by service as those tickets land; absent pieces
# are noted, never faked. Teardown: this script kills only what it started.
set -e
cd "$(dirname "$0")/../.."

: "${DATABASE_URL:?set DATABASE_URL (postgres on :5433 per docker-compose)}"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.dev}"

uv run python manage.py migrate
uv run python manage.py seed_demo --e2e

if curl -sf --max-time 2 localhost:8000/healthz >/dev/null 2>&1; then
  echo "port 8000 already serves bookr — kill the stray runserver first"
  exit 1
fi

uv run python manage.py runserver 8000 >/tmp/bookr-e2e-web.log 2>&1 &
WEB_PID=$!
trap 'kill $WEB_PID 2>/dev/null' EXIT

echo "-- waiting for web (bounded: 60s, never bare sleeps, always readiness) --"
for _ in $(seq 1 60);
do
  if curl -sf --max-time 2 localhost:8000/healthz >/dev/null; then
    break
  fi
  if [ "$_" -eq 60 ]; then
    echo "web never became ready; see /tmp/bookr-e2e-web.log"
    exit 1
  fi
  sleep 1
done

if [ -n "${REDIS_URL:-}" ]; then
  uv run celery -A config worker --detach 2>/dev/null || true
  echo "-- worker: real broker at REDIS_URL --"
else
  echo "-- worker: none (CELERY_EAGER=1, tasks run inline) --"
fi
if [ -n "${FRONTEND_URL:-}" ]; then
  echo "-- frontend: $FRONTEND_URL --"
else
  echo "-- frontend: none (browser specs skip) --"
fi
if [ -n "${MAILPIT_URL:-}" ]; then
  echo "-- mailpit: $MAILPIT_URL --"
else
  echo "-- mailpit: none (mail assertions stay at unit level) --"
fi

DATABASE_URL="$DATABASE_URL" uv run pytest tests/e2e -m smoke -q
