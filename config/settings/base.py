"""Base settings: everything environment-agnostic. Secrets and
environment behavior live in dev.py / prod.py — never here."""

import os
from pathlib import Path

import dj_database_url

# config/settings/base.py → repo root.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


# Application definition

INSTALLED_APPS = [
    "organizations.apps.OrganizationsConfig",
    "scheduling.apps.SchedulingConfig",
    "booking.apps.BookingConfig",
    "passes.apps.PassesConfig",
    "access.apps.AccessConfig",
    "aggregators.apps.AggregatorsConfig",
    "django.contrib.postgres",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_extensions",
    "rest_framework",
    "drf_spectacular",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.VenueMiddleware",
]

ROOT_URLCONF = "config.urls"

CACHES = {
    # Locmem here and in tests; prod points this at Redis (docker ticket
    # 4cs owns the service + django-redis wiring). TTLs stay the same.
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Celery: eager inline in dev/test (no broker needed); prod sets
# CELERY_EAGER=0 and runs worker/beat (services owned by docker ticket 4cs).
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_EAGER", "1") == "1"
CELERY_BEAT_SCHEDULE = {
    "expire-passes": {
        "task": "passes.expire_passes",
        "schedule": 86400.0,
    },
}

# Mail: MAILERS rule here (console in dev, SMTP in prod via EMAIL_HOST*
# env). Templates live in booking/notify.py (cancelled/promoted/late-cancel).
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "bookr@example.com")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "config.exceptions.exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Bookr API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases
# Single definition, strictly from the environment: a missing DATABASE_URL
# fails here at import (KeyError naming it), never as a mystery later.
DATABASES = {
    "default": dj_database_url.parse(
        os.environ["DATABASE_URL"],
        conn_max_age=600,  # persistent conns; drop to 0 behind a pooler later
        conn_health_checks=True,  # recycle dead conns instead of failing
    ),
}
# Services own their transactions (booking/ledger use explicit atomic blocks),
# so ATOMIC_REQUESTS stays off. Default READ COMMITTED is correct for
# SELECT ... FOR UPDATE. Test DBs build from migrations, which include
# CreateExtension("btree_gist") (lesson 3) — no manual step.


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# WhiteNoise serves the Vite build (assets) at root; the catch-all view in
# config/urls.py serves index.html for app routes. No dist in dev: 404s.
WHITENOISE_ROOT = BASE_DIR / "frontend" / "dist"
