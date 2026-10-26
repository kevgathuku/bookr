"""Local development: everything from .env (see .env.example)."""

import os

from .base import *

DEBUG = True

# Strict like everything else here: dev still fails loudly without its env.
SECRET_KEY = os.environ["SECRET_KEY"]

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.console.EmailBackend",
    },
}
