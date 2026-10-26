"""Production: every secret and host comes from the environment.
See https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/"""

import os

from .base import *

DEBUG = False

SECRET_KEY = os.environ["SECRET_KEY"]

ALLOWED_HOSTS = os.environ["ALLOWED_HOSTNAMES"].split(",")

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "HOST": os.environ.get("EMAIL_HOST", "localhost"),
        "PORT": int(os.environ.get("EMAIL_PORT", "25")),
        "USERNAME": os.environ.get("EMAIL_USERNAME", ""),
        "PASSWORD": os.environ.get("EMAIL_PASSWORD", ""),
        "USE_TLS": os.environ.get("EMAIL_USE_TLS", "True") == "True",
    },
}
