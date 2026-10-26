# Bookr — Gym Management Spec

Multi-tenant Django app for individual gyms: group classes, 1-1 appointments, passes/credits, aggregator distribution, self-service access control.

## 1. Goals / Non-goals

Goals: one deploy serves many gyms (tenant = `Gym`); correct bookings under concurrency; auditable credit ledger; aggregators as just another booking channel; doors open/deny in <500ms.
Non-goals (v1): payments/PSP integration, native mobile apps, dynamic pricing, marketing CRM.

## 2. Tenancy & Roles

- Tenancy: single DB, shared schema, every tenant-scoped row has `gym FK`. Enforce via middleware (`X-Gym-Slug` / staff's gym) + queryset mixin `GymScopedManager`. No cross-gym FKs. Unique constraints scoped to `(gym, ...)`.
- Roles (per gym): `owner, manager, teacher, frontdesk, member`. Use Django groups + per-object check (`is_teacher_of(class)`). Staff ≠ superuser. Aggregator access via scoped API tokens, never user passwords.

## 3. Domain

### 3.1 Scheduling (classes)

Models: `ClassType(name, description, capacity_default, duration_min)`, `Studio/Room(name, capacity)`, `ScheduledClass(class_type, room, teacher, starts_at, ends_at, capacity_override, status: scheduled|cancelled|completed, checkin_opens_min=30)`, `TeacherSubstitution(scheduled_class, old_teacher, new_teacher, reason, created_by)` (append-only, keep history).

Rules:
- No double-booked room or teacher: `ExclusionConstraint` on `TSTZRANGE(starts_at, ends_at)` per `(gym, room)` and `(gym, teacher)` where `status != cancelled` (requires Postgres + btree_gist).
- Capacity = override or room capacity or type default (first non-null wins). Capacity edits never kick confirmed bookings; only shrink free seats.
- Class cancellation by staff → auto-refund credits + notify confirmed + promote waitlist in order. Immutable once `completed`.
- Substitution notifies booked members; original teacher record kept.

### 3.2 Bookings, waitlist, late cancels

Models: `Booking(idempotency_key, member, scheduled_class NULL, appointment NULL, status: confirmed|waitlisted|cancelled|no_show|completed, source: app|frontdesk|aggregator:<name>, credit_tx FK, checked_in_at)`; `WaitlistEntry(booking UNIQUE, position)` or derive position by `created_at` — prefer derived, one less counter to corrupt.

Rules:
- One active booking per member per class: `UniqueConstraint(gym, member, scheduled_class) WHERE status IN (confirmed, waitlisted)`.
- Booking is a transaction: `SELECT ... FOR UPDATE` on `ScheduledClass` row (or `select_for_update` on a `SeatCounter`) → check seats → deduct credit → create booking. Serialize per class. Return `409` when full (offer waitlist join in same call via `?waitlist=true`).
- Waitlist promotion FIFO by `created_at`, on cancel/no-show/capacity increase. Promotion holds seat for `hold_ttl_min` (default 60, configurable per gym); expiry passes to next. Promotion runs in Celery task, idempotent on `booking_id`.
- Late-cancel window per gym (default 8h classes, 24h 1-1): cancel inside window → `cancelled_late`, credit forfeited (configurable `forfeit_late_cancel bool`), counts toward no-show strikes. Outside window → refund to ledger. Staff override always refunds with `reason` logged.
- No-show: frontdesk marks within 2h after end → forfeit credit. 3 strikes in 30d → optional booking throttle (flag, don't auto-ban in v1).

### 3.3 1-1 appointments & resources

Models: `Resource(type: room|equipment|teacher, name, gym)`, `AvailabilityRule(resource, weekday, start_time, end_time, valid_from, valid_to)`, `AvailabilityException(resource, date, start/end or closed)`, `Appointment(member, teacher, resource NULL, starts_at, ends_at, status)`.

Rules:
- Availability = weekly rules minus exceptions minus existing appointments/classes involving that teacher/resource. Compute in Python (`generate_slots(rule, date)`), never store every slot.
- Same exclusion constraints as classes for `(gym, teacher)` and `(gym, resource)`.
- Buffer time per gym (`buffer_min` default 10) pads both sides for conflict checks.
- Calendar display: API returns events for a date range (`GET /api/calendar?from&to&teacher&room`), frontend renders (FullCalendar). Never `SELECT *` — always bounded range, max 31d.

### 3.4 Passes & credits

Models: `PassProduct(name, credits_total or unlimited, validity_days, applicable_class_types M2M blank=all, transferable=False)`, `MemberPass(member, product, credits_total, credits_used, valid_from, valid_until, status)`, `CreditLedger(pass FK, booking FK NULL, delta, reason: purchase|booking|refund|forfeit|expiry|adjustment, created_by, created_at)` — ledger is append-only, balance = `SUM(delta)`.

Rules:
- Booking consumes exactly 1 credit (v1; keep `credits_cost` column default 1 for later pricing). FIFO: oldest valid pass covering the class type first. Unlimited passes checked before credit ones.
- Expiry via nightly Celery task writes `forfeit/expiry` ledger rows; never delete or mutate `credits_used` directly — always append to ledger and update cached counters in same transaction.
- Refunds append `+1 refund` rows referencing original booking. Staff adjustments require `reason` + staff id (audit).
- Race safety: `select_for_update` on chosen `MemberPass` row during booking.

### 3.5 Aggregators (ClassPass-style)

Models: `Aggregator(name, api_token_hash, seat_allotment, cutoff_min, commission_pct, active)`, `AggregatorBooking(map to Booking.source=aggregator:<name>, external_id UNIQUE per aggregator)`.

Rules:
- Separate API surface: `POST /api/v1/aggregators/<slug>/bookings` with token auth (hashed, per-aggregator, rotatable) + rate limit. Allotment enforced: aggregator bookings per class ≤ `min(allotment, free seats)`.
- Idempotency required: `(aggregator, external_id)` unique; retries with same key return original booking. Webhook/cancel symmetric. Log every inbound request (`AggregatorEventLog`) for reconciliation.
- Availability push: read-only `GET .../schedule?from&to` + optional webhook on class change (Celery, retry with backoff, sign payloads HMAC).
- Aggregator bookings never consume member passes — billed to aggregator account monthly. Late-cancel policy from contract (`cutoff_min` per aggregator) applies instead of gym default.

### 3.6 Access control (self-service doors)

Models: `AccessPoint(name, controller_id, gym)`, `AccessEvent(member NULL, access_point, granted bool, reason, booking_id NULL, occurred_at)`.

Rules:
- Grant iff: active pass OR confirmed booking starting within `[-15min, +class duration]` OR staff role. Deny otherwise, always log.
- Door controllers call `POST /api/access/check` (token auth per controller, p95 <200ms): read-only check, no credit deduction. Cache member validity in Redis (TTL 60s) with DB fallback; fail-closed on DB outage (deny + log) — shortcut: fail-closed only, auto-open on outage is out of scope.
- Anti-passback: same member re-entry within 60s returns prior decision without new event (configurable).

## 4. API & Project Layout

- Django 5 + DRF for `/api/*`, `djangorestframework-simplejwt` (app) + token auth (aggregators/controllers). Versioned: `/api/v1/`. OpenAPI via `drush`/`drf-spectacular`, breaking change = new version.
- Proposed layout (create on `django-admin startproject`):
  ```
  bookr/ (settings/, urls.py)  apps/: gyms/ scheduling/ bookings/ passes/ aggregators/ access/ members/
  ```
  One app per §3 section. Cross-app imports only via services (`bookings/services.py::book_seat()`), never model-to-model shortcuts.
- Settings: `django-environ`, split `base/dev/prod`; Postgres + `pgcrypto/btree_gist`; Redis (cache + Celery broker); `TIME_ZONE` per gym, store all datetimes UTC.
- Background: Celery + Beat — waitlist promotion, expiry sweeps, aggregator webhooks, reminders/notifications (email/SMS via pluggable backend, templates per gym).
- Money-adjacent discipline: ledger append-only, `select_for_update` on booking paths, `idempotency_key` unique on `Booking`, admin actions logged (`LogEntry` + `reason`).

## 5. Quality Bar

### Django best practices
- Fat services/models, thin views: no business logic in views/serializers; services raise typed errors (`SeatFull`, `CreditInsufficient`), views map to status codes.
- Validation at trust boundary: serializers validate; constraints (`Check/Unique/Exclusion`) enforce at DB as backstop. `select_related/prefetch_related` everywhere list-shaped; assert `assertNumQueries` in list tests.
- AuthZ: `IsAuthenticated` + per-gym permission class (`IsGymMember`) on every viewset; tests hit cross-gym access (must 404, not 403, to avoid id leaks).
- Migrations: generated, reviewed, `sqlmigrate` for exclusion constraints; data migrations batched. Never `RunPython` without reverse.
- Observability: structured logs with `gym_id/booking_id`, Sentry, `/healthz`, Prometheus metrics (`bookings_total{status}`, `door_grants_total`).

### Testing
- Unit (pytest-django + factory-boy, fast, no I/O): service functions — FIFO pass deduction, late-cancel forfeit vs refund boundary (±1 min), waitlist ordering, availability math (DST edge), allotment enforcement. Target ≥80% on `services.py`/ledger.
- Concurrency test (required, not optional): `ThreadPoolExecutor` N threads booking last seat → exactly 1 confirmed, N-1 waitlisted/409. Same for double-credit-spend.
- API tests (DRF APITestCase): happy path + 409 full + idempotent retry + cross-gym isolation + aggregator token scope.
- E2E (Playwright, few but real): member books → waitlisted → staff cancels seat → member promoted + email received (mailpit); late cancel forfeits credit visible in ledger; door check grants/denies. Run against docker-compose (db+redis+web+worker) in CI; tag `@e2e`, nightly + pre-release, not per-commit if slow.
- CI: `ruff + black --check, mypy (services/models), pytest -x, playwright @smoke`. Seed demo gym via management command for local dev.

## 6. Build Order

1. gyms+members+auth, 2. classes+booking tx + tests, 3. waitlist/late-cancel + Celery, 4. passes/ledger, 5. appointments/availability+calendar, 6. aggregators, 7. access control. Ship 1–4 as MVP.
