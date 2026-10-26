# Bookr Resources

## Knowledge

- [Django documentation](https://docs.djangoproject.com/) — the framework reference. Use for: ORM, transactions (`select_for_update`), testing, migrations.
- [Django REST Framework](https://www.django-rest-framework.org/) — API layer. Use for: viewsets, permissions, throttling, token auth.
- [PostgreSQL: Exclusion constraints + btree_gist](https://www.postgresql.org/docs/current/btree-gist.html) — the no-double-booking mechanism. Use for: Chapters 2 and 6 constraints.
- [PostgreSQL: Range types](https://www.postgresql.org/docs/current/rangetypes.html) — `TSTZRANGE` semantics behind the constraints above.
- [Celery docs](https://docs.celeryq.dev/) — background work. Use for: waitlist promotion, expiry sweeps, webhook retries, Beat schedules.
- [pytest-django](https://pytest-django.readthedocs.io/) + [factory-boy](https://factoryboy.readthedocs.io/) + [freezegun](https://github.com/spulec/freezegun) — the unit-test stack. Use for: service tests, boundary tests, hold-expiry tests.
- [Playwright for Python](https://playwright.dev/python/) — E2E. Use for: promotion-with-email and door grant/deny flows.
- [FullCalendar](https://fullcalendar.io/docs) — calendar display. Use for: rendering the Chapter 6 events endpoint.
- [drf-spectacular](https://drf-spectacular.readthedocs.io/) — OpenAPI schema for the versioned API.

## Wisdom (Communities)

- [Django Forum](https://forum.djangoproject.com/) — moderated, core-dev presence. Use for: ORM/transaction puzzles, Postgres constraint questions.
- [r/django](https://www.reddit.com/r/django/) — large, practical. Use for: deployment and Celery-in-production reality checks.

## Gaps

- Aggregator partner specifics (allotments, cutoffs, reconciliation formats) — ClassPass-style partner docs are gated per contract; the spec's terms stand in until a real contract lands.
