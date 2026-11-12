# Bookr Tutorial — Build It Chapter by Chapter

In the spirit of the Flask Mega-Tutorial: small working app at the end of every chapter, each chapter builds on the last. By the end you have a multi-tenant venue manager with classes, credits, aggregators, and door access.

How to use this: do the chapters in order. Each ends with **Run it** (proof it works) and **Exercises** (do at least #1). Code sketches are minimal — grow them, don't copy-paste blindly. The contract is `SPEC.md`; this is the walking path.

## Chapter 0: What you're building

A single Django deploy serving many venues. A member books a class seat, pays with pass credits, can waitlist, can be late-cancelled, can come via an aggregator (ClassPass-style), and can open the venue door with a booking. Staff manage subs, rooms, availability.

You'll need: Python 3.14+, Docker (services run in containers until Chapter 10 orchestrates them), Django 6.1 (pinned in `pyproject.toml`), plus working web-development knowledge (HTTP, ORM concepts, background jobs). No prior Django needed — same deal as the official Django tutorial: you bring web experience, the course teaches Django's opinions.

**Exercises:** 1) Read `SPEC.md` §§1–3 once end to end.

## Chapter 1: Project skeleton + multi-tenancy

**Goal:** Postgres runs, migrations apply, and every row belongs to exactly one venue.

1. `django-admin startproject config .`, then create only what this chapter needs: `startapp organizations` (`Organization` + `Venue` + `VenuePolicy` + `Membership` live there together — the whole tenancy context in one app). Each later chapter adds its own app the same way — nothing before its time, and never one shared app "for simplicity" (you'll regret it by Chapter 6).
2. Baseline deps: `uv add "django>=6.1,<7" django-environ "psycopg[binary]"` (`psycopg` v3 is the driver Django 6 talks to; add DRF / Celery / `redis` in the chapters that use them, always latest releases). Then start the database: `docker compose up -d db` (the compose file holds only `db` for now; Redis and mailpit join it in Chapter 4, the rest in Chapter 10), with `DATABASE_URL` in a local `.env` (see README) for the `django-environ` settings split (`base/dev/prod`). Generated settings already ship `USE_TZ = True` + `TIME_ZONE = 'UTC'` — keep datetimes UTC, per-venue `time_zone` is display-only.
3. Tenancy core in `organizations`: `Organization(slug UNIQUE, name, membership_scope=spanning|per_venue)` → `Venue(org, slug UNIQUE per org, name, time_zone)` + `VenuePolicy` versions holding the business rules (never edited: retire stamps `valid_until`, activate inserts a row; one active row per venue, read via `venue.current_policy`). Scoped unique constraints everywhere: `(venue, ...)` (slugs: `(organization, ...)`). (Request handling — middleware, permissions — arrives in Ch.2 with the first endpoint.)
4. Roles: `owner/manager/teacher/frontdesk/member` per membership, via `Membership(org, venue NULL when spanning, user, role)` — the role field is authoritative, not Django Groups (ADR-0005). Scope is set per organization: spanning orgs cover all venues with one row; per-venue orgs pin each row (enforced at creation). (The `IsVenueMember` permission enforcing it arrives in Ch.2.)

**Run it:** `uv run pytest tests -q` — model constraint tests green. `GET /healthz` → 200.
**Exercises:** 1) Add a model test per constraint in `tests/`. 2) Add `seed_demo` management command (2 orgs + venues + users, re-runnable; rooms/classes extend it in Ch.2, passes in Ch.5) — later chapters build on it.

## Chapter 2: Class types, rooms, schedule

**Goal:** staff can publish a weekly schedule that can't double-book.

1. New app first: `... startapp scheduling`. Then models: `ClassType`, `Room`, `ScheduledClass(... status)`, `TeacherSubstitution` (append-only, §3.1). Capacity resolution: override → room → type default.
2. The important line: Postgres `ExclusionConstraint` on `TSTZRANGE(starts_at, ends_at)` for `(venue, room)` and `(venue, teacher)` where active. Check `sqlmigrate` output by eye — this is the constraint that saves you at 6pm on Monday.
3. DRF (`uv add djangorestframework`): `GET /api/v1/classes?from&to` (bounded, max 31d, `select_related`), scoped through a shared `VenueScopedManager` mixin (`for_venue()` — defined here, at first use), staff-only POST/PATCH. Cancelling a class sets `cancelled` and logs a fan-out line (it becomes the Celery fan-out in Ch.4).
4. Substitution: POST creates row, keeps old teacher, notifies (log in dev, mailpit from Ch.4 on).
5. First wired requests: add the venue middleware (resolve from staff membership, else `X-Venue-Slug`, org derived from venue — one choke point so no view forgets scoping) and the `IsVenueMember` permission (spanning-or-pinned `Q`, filter-then-404 so outsiders can't enumerate). Prove it with three isolation tests: org-A member on org-B's object → 404; pinned member on venue B → 404; spanning member → 200 on both.

**Run it:** create two overlapping classes same room in the shell — second must `IntegrityError`. List endpoint: `assertNumQueries` ≤ 3. Isolation trio green (404, 404, 200).
**Exercises:** 1) Capacity-shrink test: reducing capacity below confirmed count keeps bookings, shrinks free seats only. 2) The isolation trio, if not written in step 5.

## Chapter 3: Bookings — the money moment

**Goal:** exactly one member gets the last seat, even under concurrency.

1. New app: `... startapp bookings`. Model: `Booking(idempotency_key UNIQUE, member, scheduled_class NULL, appointment NULL, status, source, credit_tx FK)` + `UniqueConstraint(venue, member, scheduled_class) WHERE active`.
2. `bookings/services.py::book_seat(member, klass, *, waitlist=False, idempotency_key)` — the only function that creates bookings. Thin views, fat service. Inside `transaction.atomic`: `select_for_update` the class row → count confirmed → if full and not waitlist → raise `SeatFull` (view → 409 + offer `?waitlist=true`) → else deduct credit (stub: always succeeds until Ch.5) → create booking.
3. Views map typed errors to codes: `SeatFull→409`, `CreditInsufficient→402`, `DuplicateBooking→409`. Member login arrives here too (`uv add djangorestframework-simplejwt`) — the book endpoint authenticates the member; everything else stays service-level. No business logic in views/serializers.

**Run it:** the concurrency test (required, §5): `ThreadPoolExecutor` × 20 threads on 1 free seat → exactly 1 confirmed. If this fails, stop — nothing later matters.
**Exercises:** 1) Idempotent retry test: same key twice → one booking. 2) Double-book same member same class → 409.

## Chapter 4: Waitlist, late cancels, no-shows

**Goal:** cancellations heal themselves; late cancels cost a credit.

1. Waitlist = FIFO by `Booking.created_at` (derive position, don't store counters). `cancel_seat()` runs in transaction, then enqueues `promote_waitlist(class_id)` (Celery, idempotent on booking id). Promotion holds seat `waitlist_hold_minutes`; expiry → next in line. Same-code path for cancel, no-show, capacity increase.
2. `cancel_booking(member, booking, by_staff=False)`: inside/outside `venue.current_policy.class_late_cancel_hours` → `cancelled_late` (forfeit, counts to strikes) vs `cancelled` (refund — stub ledger call until Ch.5, log it). Staff override always refunds with `reason`.
3. No-show: frontdesk `POST .../no_show` within 2h after end → forfeit. 3 strikes/30d → flag member (don't auto-ban in v1).
4. New infra: `uv add celery redis`; compose gains `redis` + `mailpit` services, while `worker` and `beat` run as plain processes for now (`uv run celery -A config worker` / `... beat` — they move into compose in Chapter 10); `REDIS_URL` + `EMAIL_URL` in dev settings. Notifications via that pluggable backend (console → mailpit), per-venue templates. Wire class-cancelled, promoted, late-cancel-receipt now.

**Run it:** E2E #1 (Playwright, mailpit): book → full → waitlist → staff cancels a seat → first waitlisted promoted + email arrives.
**Exercises:** 1) Boundary test: cancel at `window ± 1 min` → refund vs forfeit. 2) Hold-expiry test with freezegun.

## Chapter 5: Passes & the credit ledger

**Goal:** every credit movement is auditable; races can't double-spend.

1. New app: `... startapp passes`. Models: `PassProduct`, `MemberPass`, `CreditLedger(pass, booking NULL, delta, reason, created_by)` — append-only. Balance = `SUM(delta)`; cached counters updated in the same transaction, never edited directly.
2. `passes/services.py::spend_credit(member, booking)` — `select_for_update` chosen pass, FIFO oldest-valid-first covering the class type, unlimited passes first. `refund_credit`, `adjust_credit(reason, staff)` (reason required), nightly `expire_passes` Beat task writing expiry rows.
3. Go back and replace the Ch.3 stub: `book_seat` now calls `spend_credit`; `cancel_booking` calls `refund` or `forfeit` per Ch.4 rules.
4. Expose `GET /api/v1/me/passes` + ledger view (member sees own; frontdesk sees venue's).

**Run it:** spend-last-credit race (20 threads, 1 credit) → exactly 1 booking. Ledger sum equals cached balance for every pass in seed data (add an invariant test).
**Exercises:** 1) Expiry sweep test: expired pass → expiry ledger row, booking with it → 402. 2) Staff adjustment without reason → 400.

## Chapter 6: 1-1 appointments, availability, calendar

**Goal:** bookable humans and rooms with one calendar endpoint.

1. No new app — appointments extend `scheduling`. Models: `Resource`, `AvailabilityRule(weekday, start/end, valid range)`, `AvailabilityException`, `Appointment`. Slots are **computed** (`generate_slots(rule, date)` minus exceptions minus existing commitments), never stored. Same exclusion constraints for `(venue, teacher)`, `(venue, resource)`; `booking_buffer_minutes` pads conflict checks.
2. `GET /api/v1/calendar?from&to&teacher&room` merges classes + appointments, bounded 31d. Pair with FullCalendar on the frontend — backend just returns events fast (`prefetch_related`, pagination by day).
3. Late-cancel for appointments uses `appointment_late_cancel_hours` (default 24h).

**Run it:** create overlapping appointment for same teacher → `IntegrityError`. Calendar for a week renders in <200ms on seed data.
**Exercises:** 1) DST-boundary availability test. 2) Buffer test: back-to-back with `booking_buffer_minutes=10` conflicts.

## Chapter 7: Access control — the door

**Goal:** `POST /api/access/check` grants or denies in <200ms, and every knock is logged.

1. New app: `... startapp access`. Models: `AccessPoint(controller_id, venue)`, `AccessEvent(member NULL, point, granted, reason, booking NULL)`. Grant iff: active pass OR confirmed booking in `[-15min, +duration]` OR staff role. Controllers use per-device tokens, dedicated lightweight view (no DRF bloat in the hot path if needed).
2. Redis cache member-validity TTL 60s, DB fallback. **Fail-closed**: DB down → deny + log. Anti-passback: same member 60s → replay prior decision.
3. Log everything, expose recent events to frontdesk.

**Run it:** E2E #2: member with upcoming booking → grant; expired pass + no booking → deny; both rows in `AccessEvent`. Kill DB in staging → deny (fail-closed drill).
**Exercises:** 1) Load test the check endpoint (k6/locust, p95 target). 2) Passback test.

## Chapter 8: Tests, CI, ship

**Goal:** the suite you trust and the pipeline that runs it.

1. New dev deps: `uv add --dev pytest pytest-django factory-boy freezegun playwright ruff black mypy`. Grow the day-one `tests/` into this layout: `tests/unit` (services, ledger math, availability — fast, `pytest-django` + `factory-boy` + `freezegun`, ≥80% on services), `tests/api` (DRF status codes, isolation, idempotency), `tests/e2e` (Playwright `@e2e` against the running app + mailpit asserts). Concurrency tests from Ch.3/Ch.5 live in unit and run in CI.
2. CI: `ruff + black --check` → `mypy` (services/models) → `pytest -x` → Playwright `@smoke`. Full `@e2e` nightly + pre-release.
3. Ship checklist: `sqlmigrate` reviewed, demo seed works from zero, `/healthz` + Sentry + structured logs (`venue_id/booking_id`), token rotation runbook, fail-closed drill done.

**Run it:** green CI on a fresh clone following only this tutorial.
**Exercises:** 1) Delete your db, rebuild from migrations + seed. 2) Write the postmortem template before you need it.

## Chapter 9: Aggregators — strangers booking your classes

**Goal:** an external platform books seats without touching member passes.

**Phase 2 — do not start until Chapters 1–8 are validated** (green CI, one venue fully working). Aggregators multiply every booking-path bug onto a partner's platform; earn them with a proven core.

1. New app (Phase 2): `... startapp aggregators`. Models: `Aggregator(slug, api_token_hash, seat_allotment, cancel_cutoff_minutes, commission_percent, active)` + `AggregatorBooking(aggregator, external_id UNIQUE per aggregator → Booking)`. Separate router `POST /api/v1/aggregators/<slug>/bookings` with per-aggregator token auth (hashed, rotatable) + throttling. `AggregatorEventLog` records every inbound call.
2. Enforce `min(allotment, free seats)`; `(aggregator, external_id)` idempotent retries return the original. Their late-cancel uses contract `cancel_cutoff_minutes`, billed to aggregator account — never member passes.
3. Outbound: read-only `GET .../schedule?from&to` + HMAC-signed webhooks on class change (Celery retry w/ backoff).

**Run it:** book same `external_id` twice → one booking; exceed allotment → 409; rotate token → old token 401s.
**Exercises:** 1) Reconciliation test: event log replays to identical booking state. 2) Webhook signature verification test.

## Chapter 10: Docker — the pre-deployment dress rehearsal

**Goal:** the verified app runs from images, not your laptop. Do this after Chapter 9 is green, before touching any cloud.

1. Install the server (`uv add gunicorn`), then write a `Dockerfile` (multi-stage: `uv sync --frozen`, then a slim runtime running `gunicorn config.wsgi`; non-root user; `collectstatic` at build; no secrets baked in — everything via environment).
2. Grow the compose file: add `web`/`worker`/`beat` (the worker and beat move in from their terminals) and write `docker-compose.prod.yml`: `web` (gunicorn, `$PORT`), `worker`, `beat`, `db`, `redis`. Migrations run as a one-off (`docker compose run web python manage.py migrate`), never inside the boot command.
3. Create `.env.prod` for `django-environ`: `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `ALLOWED_HOSTS`, `EMAIL_URL`. Dev's mailpit stays in the dev file; prod points at the real sender.
4. Boot it: `docker compose -f docker-compose.prod.yml up --build`, migrate, then (staging only) `seed_demo`. Run the `@smoke` suite against the containers and click through one booking by hand; check `/healthz`, structured logs, and admin login.
5. Prove reproducibility: `docker compose down -v`, rebuild from zero, migrate, re-run smoke. If it isn't green from scratch, it isn't shippable.

**Run it:** fresh `up --build` on a clean machine state → migrate → smoke green → one manual booking.
**Exercises:** 1) `docker scout`/`dive` the image and justify every layer. 2) Time the cold boot; write the rollback runbook (previous image tag + migrate backwards plan).

## Build order reminder

Ch.1 → Ch.2 → Ch.3 → Ch.4 → Ch.5 → Ch.6 → Ch.7 → Ch.8 → Ch.9 → Ch.10. MVP = Chapters 1–5. Chapters 1–8 are the single-venue product — validate it (green CI, working venue) before Phase 2 (Ch.9 aggregators). Don't ship anywhere before Chapter 10 is green.
