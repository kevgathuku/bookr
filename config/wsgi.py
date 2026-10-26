"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

# No default here — WSGI serves real traffic, so the environment must say
# which settings to use (e.g. DJANGO_SETTINGS_MODULE=config.settings.prod).
if "DJANGO_SETTINGS_MODULE" not in os.environ:
    raise RuntimeError("DJANGO_SETTINGS_MODULE is not set (want config.settings.prod?)")

application = get_wsgi_application()
