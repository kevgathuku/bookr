"""Test settings: dev shape with local-first defaults and speed tweaks.

Defaults point at a dedicated `bookr_test` database on the documented
compose-mapped Postgres (`docker-compose.yml` maps db to host :5433) — never
the dev `bookr` database; CI overrides via env
(`setdefault` never clobbers an existing value). SECRET_KEY has a dummy
default so `uv run pytest` needs no prefixes. MD5 hasher keeps the suite
fast; debug toolbar stays off.
"""

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgres://bookr:bookr@localhost:5433/bookr_test",
)
os.environ.setdefault("SECRET_KEY", "test-only-insecure-key")

from .dev import *

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "debug_toolbar"]
MIDDLEWARE = [
    middleware for middleware in MIDDLEWARE if "debug_toolbar" not in middleware
]
