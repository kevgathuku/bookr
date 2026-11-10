#!/bin/sh
# Render free has no pre-deploy step and its Docker Command field does not
# run through a shell, so `sh -c "migrate && gunicorn"` fails there.
# Single executable instead: migrate (idempotent) then serve on $PORT.
set -e
python manage.py migrate
exec gunicorn config.wsgi --bind "0.0.0.0:${PORT:-8000}" --workers 2
