"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

# No default here — ASGI serves real traffic, so the environment must say
# which settings to use (e.g. DJANGO_SETTINGS_MODULE=config.settings.prod).
# get_asgi_application() raises ImproperlyConfigured if it is unset.
if "DJANGO_SETTINGS_MODULE" not in os.environ:
    raise RuntimeError("DJANGO_SETTINGS_MODULE is not set (want config.settings.prod?)")

application = get_asgi_application()
