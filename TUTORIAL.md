# Bookr Tutorial — Build It Chapter by Chapter

In the spirit of the Flask Mega-Tutorial: small working app at the end of every chapter, each chapter builds on the last. By the end you have a multi-tenant gym manager with classes, credits, aggregators, and door access.

How to use this: do the chapters in order. Each ends with **Run it** (proof it works) and **Exercises** (do at least #1). Code sketches are minimal — grow them, don't copy-paste blindly. The contract is `SPEC.md`; this is the walking path.

## Chapter 0: What you're building

A single Django deploy serving many gyms. A member books a class seat, pays with pass credits, can waitlist, can be late-cancelled, can come via an aggregator (ClassPass-style), and can open the gym door with a booking. Staff manage subs, rooms, availability.

You'll need: Python 3.12+, Docker (Postgres + Redis), familiarity with Django ORM basics. That's it.

**Exercises:** 1) Read `SPEC.md` §§1–3 once end to end.

## Chapter 1: Project skeleton + multi-tenancy

**Goal:** `docker compose up` gives you web + db + redis + worker, and every row belongs to a gym.

1. `django-admin startproject config .` then create apps: `gyms members scheduling bookings passes aggregators access`. One app per spec section — don't merge them "for simplicity," you'll regret it at Chapter 6.
2. Add `docker-compose.yml` (web, db w/ `btree_gist`, redis, celery worker, beat, mailpit), `django-environ` settings split (`base/dev/prod`), all datetimes UTC, per-gym `time_zone` field only for display.
3. Tenancy core in `gyms`: `Gym(slug UNIQUE, name, time_zone, late_cancel_h=8, appt_late_cancel_h=24, forfeit_late_cancel=True, hold_ttl_min=60, buffer_min=10)` + `GymScopedManager` (filters `gym=`) + middleware resolving gym from staff profile or `X-Gym-Slug` header for API. Scoped unique constraints everywhere: `(gym, ...)`.
4. Roles: Django groups `owner/manager/teacher/frontdesk/member` per gym via a `Membership(user, gym, role)` model. Permission class `IsGymMember` — cross-gym access returns **404**, not 403 (no id leaks).

**Run it:** `pytest apps/gyms` — test that gym A's member 404s on gym B's endpoint. `GET /healthz` → 200.
**Exercises:** 1) Write the cross-gym 404 test. 2) Add `seed_demo` management command (1 gym, 1 room, 1 teacher, 5 members) — you'll reuse it every chapter.

## Chapter 2: Class types, rooms, schedule

**Goal:** staff can publish a weekly schedule that can't double-book.

1. Models: `ClassType`, `Room`, `ScheduledClass(... status)`, `TeacherSubstitution` (append-only, §3.1). Capacity resolution: override → room → type default.
2. The important line: Postgres `ExclusionConstraint` on `TSTZRANGE(starts_at, ends_at)` for `(gym, room)` and `(gym, teacher)` where active. Check `sqlmigrate` output by eye — this is the constraint that saves you at 6pm on Monday.
3. DRF: `GET /api/v1/classes?from&to` (bounded, max 31d, `select_related`), staff-only POST/PATCH. Cancelling a class sets `cancelled`, fires the Celery fan-out (refunds + notify + promote — implemented Ch.4, stub it now with a logged no-op task).
4. Substitution: POST creates row, keeps old teacher, notifies (log in dev, mailpit from Ch.4 on).

**Run it:** create two overlapping classes same room in the shell — second must `IntegrityError`. List endpoint: `assertNumQueries` ≤ 3.
**Exercises:** 1) Capacity-shrink test: reducing capacity below confirmed count keeps bookings, shrinks free seats only.

## Chapter 3: Bookings — the money moment

**Goal:** exactly one member gets the last seat, even under concurrency.

1. `Booking(idempotency_key UNIQUE, member, scheduled_class NULL, appointment NULL, status, source, credit_tx FK)` + `UniqueConstraint(gym, member, scheduled_class) WHERE active`.
2. `bookings/services.py::book_seat(member, klass, *, waitlist=False, idempotency_key)` — the only function that creates bookings. Thin views, fat service. Inside `transaction.atomic`: `select_for_update` the class row → count confirmed → if full and not waitlist → raise `SeatFull` (view → 409 + offer `?waitlist=true`) → else deduct credit (stub: always succeeds until Ch.5) → create booking.
3. Views map typed errors to codes: `SeatFull→409`, `CreditInsufficient→402`, `DuplicateBooking→409`. No business logic in views/serializers.

**Run it:** the concurrency test (required, §5): `ThreadPoolExecutor` × 20 threads on 1 free seat → exactly 1 confirmed. If this fails, stop — nothing later matters.
**Exercises:** 1) Idempotent retry test: same key twice → one booking. 2) Double-book same member same class → 409.

## Chapter 4: Waitlist, late cancels, no-shows

**Goal:** cancellations heal themselves; late cancels cost a credit.

1. Waitlist = FIFO by `Booking.created_at` (derive position, don't store counters). `cancel_seat()` runs in transaction, then enqueues `promote_waitlist(class_id)` (Celery, idempotent on booking id). Promotion holds seat `hold_ttl_min`; expiry → next in line. Same-code path for cancel, no-show, capacity increase.
2. `cancel_booking(member, booking, by_staff=False)`: inside/outside `gym.late_cancel_h` → `cancelled_late` (forfeit, counts to strikes) vs `cancelled` (refund — stub ledger call until Ch.5, log it). Staff override always refunds with `reason`.
3. No-show: frontdesk `POST .../no_show` within 2h after end → forfeit. 3 strikes/30d → flag member (don't auto-ban in v1).
4. Notifications: pluggable backend (console → mailpit), per-gym templates. Wire class-cancelled, promoted, late-cancel-receipt now.

**Run it:** E2E #1 (Playwright, mailpit): book → full → waitlist → staff cancels a seat → first waitlisted promoted + email arrives.
**Exercises:** 1) Boundary test: cancel at `window ± 1 min` → refund vs forfeit. 2) Hold-expiry test with freezegun.

## Chapter 5: Passes & the credit ledger

**Goal:** every credit movement is auditable; races can't double-spend.

1. `PassProduct`, `MemberPass`, `CreditLedger(pass, booking NULL, delta, reason, created_by)` — append-only. Balance = `SUM(delta)`; cached counters updated in the same transaction, never edited directly.
2. `passes/services.py::spend_credit(member, booking)` — `select_for_update` chosen pass, FIFO oldest-valid-first covering the class type, unlimited passes first. `refund_credit`, `adjust_credit(reason, staff)` (reason required), nightly `expire_passes` Beat task writing expiry rows.
3. Go back and replace the Ch.3 stub: `book_seat` now calls `spend_credit`; `cancel_booking` calls `refund` or `forfeit` per Ch.4 rules.
4. Expose `GET /api/v1/me/passes` + ledger view (member sees own; frontdesk sees gym's).

**Run it:** spend-last-credit race (20 threads, 1 credit) → exactly 1 booking. Ledger sum equals cached balance for every pass in seed data (add an invariant test).
**Exercises:** 1) Expiry sweep test: expired pass → expiry ledger row, booking with it → 402. 2) Staff adjustment without reason → 400.

## Chapter 6: 1-1 appointments, availability, calendar

**Goal:** bookable humans and rooms with one calendar endpoint.

1. `Resource`, `AvailabilityRule(weekday, start/end, valid range)`, `AvailabilityException`, `Appointment`. Slots are **computed** (`generate_slots(rule, date)` minus exceptions minus existing commitments), never stored. Same exclusion constraints for `(gym, teacher)`, `(gym, resource)`; `buffer_min` pads conflict checks.
2. `GET /api/v1/calendar?from&to&teacher&room` merges classes + appointments, bounded 31d. Pair with FullCalendar on the frontend — backend just returns events fast (`prefetch_related`, pagination by day).
3. Late-cancel for appointments uses `appt_late_cancel_h` (default 24h).

**Run it:** create overlapping appointment for same teacher → `IntegrityError`. Calendar for a week renders in <200ms on seed data.
**Exercises:** 1) DST-boundary availability test. 2) Buffer test: back-to-back with `buffer_min=10` conflicts.

## Chapter 7: Aggregators — strangers booking your classes

**Goal:** an external platform books seats without touching member passes.

1. `Aggregator(slug, api_token_hash, seat_allotment, cutoff_min, commission_pct, active)` + `AggregatorBooking(aggregator, external_id UNIQUE per aggregator → Booking)`. Separate router `POST /api/v1/aggregators/<slug>/bookings` with per-aggregator token auth (hashed, rotatable) + throttling. `AggregatorEventLog` records every inbound call.
2. Enforce `min(allotment, free seats)`; `(aggregator, external_id)` idempotent retries return the original. Their late-cancel uses contract `cutoff_min`, billed to aggregator account — never member passes.
3. Outbound: read-only `GET .../schedule?from&to` + HMAC-signed webhooks on class change (Celery retry w/ backoff).

**Run it:** book same `external_id` twice → one booking; exceed allotment → 409; rotate token → old token 401s.
**Exercises:** 1) Reconciliation test: event log replays to identical booking state. 2) Webhook signature verification test.

## Chapter 8: Access control — the door

**Goal:** `POST /api/access/check` grants or denies in <200ms, and every knock is logged.

1. `AccessPoint(controller_id, gym)`, `AccessEvent(member NULL, point, granted, reason, booking NULL)`. Grant iff: active pass OR confirmed booking in `[-15min, +duration]` OR staff role. Controllers use per-device tokens, dedicated lightweight view (no DRF bloat in the hot path if needed).
2. Redis cache member-validity TTL 60s, DB fallback. **Fail-closed**: DB down → deny + log. Anti-passback: same member 60s → replay prior decision.
3. Log everything, expose recent events to frontdesk; metrics `door_grants_total`.

**Run it:** E2E #2: member with upcoming booking → grant; expired pass + no booking → deny; both rows in `AccessEvent`. Kill DB in staging → deny (fail-closed drill).
**Exercises:** 1) Load test the check endpoint (k6/locust, p95 target). 2) Passback test.

## Chapter 9: Tests, CI, ship

**Goal:** the suite you trust and the pipeline that runs it.

1. Layout: `tests/unit` (services, ledger math, availability — fast, `pytest-django` + `factory-boy` + `freezegun`, ≥80% on services), `tests/api` (DRF status codes, isolation, idempotency), `tests/e2e` (Playwright `@e2e`, docker-compose, mailpit asserts). Concurrency tests from Ch.3/Ch.5 live in unit and run in CI.
2. CI: `ruff + black --check` → `mypy` (services/models) → `pytest -x` → Playwright `@smoke`. Full `@e2e` nightly + pre-release.
3. Ship checklist: `sqlmigrate` reviewed, demo seed works from zero, `/healthz` + Sentry + structured logs (`gym_id/booking_id`), token rotation runbook, fail-closed drill done.

**Run it:** green CI on a fresh clone following only this tutorial.
**Exercises:** 1) Delete your db, rebuild from migrations + seed. 2) Write the postmortem template before you need it.

## Build order reminder

Ch.1 → Ch.2 → Ch.3 → Ch.4 → Ch.5 → Ch.6 → Ch.7 → Ch.8 → Ch.9. MVP = Chapters 1–5. Don't start aggregators before the ledger balances.
