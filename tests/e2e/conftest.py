"""E2E harness: live-server specs sharing markers with the backend suite.

- `@smoke`: per-commit. Live Django (runserver or pytest-django
  live_server), real Postgres, eager Celery. No sleeps, no mailpit, no
  frontend — those are `@e2e` (nightly) and skip without their services.
- Boot: tests/e2e/boot.sh (migrate, seed --e2e, web, readiness waits,
  smoke run). Full §5 sequence (compose, worker/beat, redis, mailpit,
  frontend preview) activates as those tickets land; absent services skip,
  never fail.
- Determinism: seed_e2e builds the fixed `e2e-run` org (fresh DB per
  CI run via down -v makes it per-run). Time boundaries stay at unit level
  (freezegun); live specs use comfortably-inside windows.
"""

import os

import pytest
import requests

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(scope="function")
def base_url(live_server):
    return live_server.url


@pytest.fixture()
def api(base_url):
    session = requests.Session()
    session.headers["Content-Type"] = "application/json"
    session.base = base_url
    return session


@pytest.fixture(autouse=True)
def seeded_db(django_db_blocker):
    """Seed inside the test DB with commits: live_server threads only
    see committed rows, so no atomic rollback here. Idempotent."""
    from django.core.management import call_command

    with django_db_blocker.unblock():
        call_command("seed_e2e")


def service_available(name, url, timeout=2):
    try:
        requests.get(url, timeout=timeout)
        return True
    except requests.RequestException:
        return False


@pytest.fixture()
def frontend_url(live_server):
    """Live Django serves the built SPA same-origin (WhiteNoise)."""
    return os.environ.get("FRONTEND_URL", live_server.url)


@pytest.fixture(scope="session")
def mailpit_url():
    url = os.environ.get("MAILPIT_URL", "")
    if not url:
        pytest.skip("MAILPIT_URL unset (mailpit arrives with compose)")
    return url
