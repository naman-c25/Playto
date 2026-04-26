#!/bin/sh
echo "=== PLAYTO BACKEND STARTING ==="
echo "PORT=$PORT"
echo "DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE"

python manage.py migrate --noinput
echo "=== MIGRATIONS DONE ==="

# Seed demo data (idempotent — get_or_create skips existing rows)
python manage.py shell < scripts/seed.py || echo "=== SEED FAILED, CONTINUING ==="
echo "=== SEED DONE ==="

exec python -m gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers 1 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --log-level debug
