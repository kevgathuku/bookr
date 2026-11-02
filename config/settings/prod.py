"""Production: every secret and host comes from the environment.
See https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/"""

import os

from .base import *

DEBUG = False

SECRET_KEY = os.environ["SECRET_KEY"]

ALLOWED_HOSTS = os.environ["ALLOWED_HOSTNAMES"].split(",")

# Shared cache: locmem in base is per-process (diverges under multi-worker
# gunicorn), so prod points at the compose Redis service instead. DB 1
# stays clear of the Celery broker on DB 0; TTLs unchanged (per-key).

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("CACHE_URL", "redis://redis:6379/1"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

# SMTP via the Django 6.1 MAILERS mapping: OPTIONS (lowercase) is the
# only accepted shape; the classic EMAIL_* settings are deprecated and
# refuse to coexist with MAILERS. The rehearsal points these at mailpit.
MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": os.environ.get("EMAIL_HOST", "localhost"),
            "port": int(os.environ.get("EMAIL_PORT", "25")),
            "username": os.environ.get("EMAIL_USERNAME", ""),
            "password": os.environ.get("EMAIL_PASSWORD", ""),
            "use_tls": os.environ.get("EMAIL_USE_TLS", "True") == "True",
        },
    },
}
