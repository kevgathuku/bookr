# Mission: Build Bookr

## Why
Ship a working multi-tenant Django app that lets individual venues run classes, bookings, credit passes, aggregator distribution, and self-service door access — going from empty repo to deployed MVP through eleven small, verifiable lessons.

## Success looks like
- `docker compose up` runs the whole platform (web, db, cache, worker) from a fresh clone
- A member can book, waitlist, cancel, and spend credits without races or double-charges
- A door controller gets a grant/deny answer in under 200ms, fail-closed on outage
- CI is green: lint, types, unit, API, and smoke E2E tests

## Constraints
- Learn by building: every lesson ends with a running checkpoint, not just reading
- Django ORM basics assumed; Postgres/Celery depth not assumed

## Out of scope
- Payments/PSP integration, native mobile apps, dynamic pricing (all v2 per spec)
- Frontend polish beyond a functional calendar view

> Draft from your tutorial context — tell me if the goal shifts and I'll update this.
