"""Production: every secret and host comes from the environment.
See https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/"""

import os

from .base import *

DEBUG = False

SECRET_KEY = os.environ["SECRET_KEY"]

ALLOWED_HOSTS = os.environ["ALLOWED_HOSTNAMES"].split(",")

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
