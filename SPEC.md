# Bookr — Venue Management Spec

Multi-tenant Django app for individual venues: group classes, 1-1 appointments, passes/credits, aggregator distribution, self-service access control.

## 1. Goals / Non-goals

Goals: one deploy serves many venues (tenant = `Venue`); correct bookings under concurrency; auditable credit ledger; aggregators as just another booking channel; doors open/deny in <500ms.
Non-goals (v1): payments/PSP integration, native mobile apps, dynamic pricing, marketing CRM.

## 2. Tenancy & Roles

- Tenancy: single DB, shared schema. `Organization` is the tenant root (the business); `Venue` is one location under it. Every tenant-scoped row carries its `venue FK`; venues carry their `organization FK`. Enforce via middleware (resolve `X-Venue-Slug`, derive the org; staff's venue from membership) + queryset mixin `VenueScopedManager`. No cross-organization FKs. Unique constraints scoped to `(venue, ...)` (slugs to `(organization, ...)`).
- Membership scope is per organization: `spanning` (one membership covers all its venues, `venue` NULL) or `per_venue` (membership pins one venue, `venue` required — enforced at creation). A teacher working two venues in a per-venue org simply holds two memberships.
- Roles (per membership): `owner, manager, teacher, frontdesk, member`. Use Django groups + per-object check (`is_teacher_of(class)`). Staff ≠ superuser. Aggregator access via scoped API tokens, never user passwords. Cross-organization or cross-venue access returns **404**, not 403 (no id leaks).

**Data model** (all fields in §3.7):

```mermaid
erDiagram
    Organization {
        string slug PK
        string name
        string membership_scope
    }
    Venue {
        string slug PK
        int organization FK
        string name
        string time_zone
    }
    VenuePolicy {
        int id PK
        int venue FK
        datetime valid_from
        datetime valid_until
        int class_late_cancel_hours
        int appointment_late_cancel_hours
        bool forfeit_late_cancel
        int waitlist_hold_minutes
        int booking_buffer_minutes
    }
    User {
        int id PK
    }
    Membership {
        int id PK
        int organization FK
        int venue FK
        int user FK
        string role
    }
    Organization ||--o{ Venue : locates
    Organization ||--o{ Membership : grants
    Venue ||--o{ Membership : pins
    Venue ||--o{ VenuePolicy : versions
    User ||--o{ Membership : holds
```

`User` is Django's auth user — no custom fields in v1. `membership_scope` ∈ spanning, per-venue; spanning rows use `venue` NULL, per-venue rows require one. Venue slugs are unique per organization. Business rules live on `VenuePolicy`, never on identity rows. Policies are versioned, never edited: retiring stamps `valid_until`, activating inserts a new row; exactly one open row per venue (partial unique on `venue` where `valid_until` is null). Read the live rules via `venue.current_policy`.

## 3. Domain

### 3.1 Scheduling (classes)

Models: `ClassType(name, description, capacity_default, duration_min)`, `Studio/Room(name, capacity)`, `ScheduledClass(class_type, room, teacher, starts_at, ends_at, capacity_override, status: scheduled|cancelled|completed, checkin_opens_minutes=30)`, `TeacherSubstitution(scheduled_class, old_teacher, new_teacher, reason, created_by)` (append-only, keep history).

Rules:
- No double-booked room or teacher: `ExclusionConstraint` on `TSTZRANGE(starts_at, ends_at)` per `(venue, room)` and `(venue, teacher)` where `status != cancelled` (requires Postgres + btree_gist).
- Capacity = override or room capacity or type default (first non-null wins). Capacity edits never kick confirmed bookings; only shrink free seats.
- Class cancellation by staff → auto-refund credits + notify confirmed + promote waitlist in order. Immutable once `completed`.
- Substitution notifies booked members; original teacher record kept.
- Venue autonomy: class types, rooms, and scheduled classes belong to exactly one venue and are never shared — a multi-location business publishes each venue's schedule separately.

**Data model** (all fields in §3.7):

```mermaid
erDiagram
    ClassType {
        int id PK
        int venue FK
        string name
        int capacity_default
        int duration_min
    }
    Room {
        int id PK
        int venue FK
        string name
        int capacity
    }
    ScheduledClass {
        int id PK
        int venue FK
        int class_type FK
        int room FK
        int teacher FK
        datetime starts_at
        datetime ends_at
        int capacity_override
        string status
        int checkin_opens_minutes
    }
    TeacherSubstitution {
        int id PK
        int scheduled_class FK
        int old_teacher FK
        int new_teacher FK
        string reason
        int created_by FK
    }
    Venue {
        int id PK
    }
    User {
        int id PK
    }
    ClassType ||--o{ ScheduledClass : types
    Room ||--o{ ScheduledClass : hosts
    User ||--o{ ScheduledClass : teaches
    ScheduledClass ||--o{ TeacherSubstitution : reassigns
```

Capacity = override → room → type default. `Venue`/`User` summarized here; full definitions in §2.

### 3.2 Bookings, waitlist, late cancels

Models: `Booking(idempotency_key, member, scheduled_class NULL, appointment NULL, status: confirmed|waitlisted|cancelled|no_show|completed, source: app|frontdesk|aggregator:<name>, credit_tx FK, checked_in_at)`; `WaitlistEntry(booking UNIQUE, position)` or derive position by `created_at` — prefer derived, one less counter to corrupt.

Rules:
- One active booking per member per class: `UniqueConstraint(venue, member, scheduled_class) WHERE status IN (confirmed, waitlisted)`.
- Booking is a transaction: `SELECT ... FOR UPDATE` on `ScheduledClass` row (or `select_for_update` on a `SeatCounter`) → check seats → deduct credit → create booking. Serialize per class. Return `409` when full (offer waitlist join in same call via `?waitlist=true`).
- Waitlist promotion FIFO by `created_at`, on cancel/no-show/capacity increase. Promotion holds seat for `waitlist_hold_minutes` (default 60, configurable per venue); expiry passes to next. Promotion runs in Celery task, idempotent on `booking_id`.
- Late-cancel window per venue (default 8h classes, 24h 1-1): cancel inside window → `cancelled_late`, credit forfeited (configurable `forfeit_late_cancel bool`), counts toward no-show strikes. Outside window → refund to ledger. Staff override always refunds with `reason` logged.
- No-show: frontdesk marks within 2h after end → forfeit credit. 3 strikes in 30d → optional booking throttle (flag, don't auto-ban in v1).
- A booking's venue must equal its class's (or appointment's) venue — enforced in the booking service, so cross-venue booking is impossible even by crafted request.

**Data model** (all fields in §3.7):

```mermaid
erDiagram
    Booking {
        int id PK
        int venue FK
        int member FK
        int scheduled_class FK
        int appointment FK
        string status
        string source
        string idempotency_key UK
        int credit_tx FK
        datetime checked_in_at
    }
    ScheduledClass {
        int id PK
    }
    Appointment {
        int id PK
    }
    CreditLedger {
        int id PK
    }
    User {
        int id PK
    }
    ScheduledClass ||--o{ Booking : fills
    Appointment ||--o{ Booking : fills
    User ||--o{ Booking : makes
    Booking ||--|| CreditLedger : pays_via
```

The waitlist has no table — order derives from `Booking.created_at`. A booking targets exactly one of class/appointment.

### 3.3 1-1 appointments & resources

Models: `Resource(type: room|equipment|teacher, name, venue)`, `AvailabilityRule(resource, weekday, start_time, end_time, valid_from, valid_to)`, `AvailabilityException(resource, date, start/end or closed)`, `Appointment(member, teacher, resource NULL, starts_at, ends_at, status)`.

Rules:
- Availability = weekly rules minus exceptions minus existing appointments/classes involving that teacher/resource. Compute in Python (`generate_slots(rule, date)`), never store every slot.
- Same exclusion constraints as classes for `(venue, teacher)` and `(venue, resource)`.
- Buffer time per venue (`booking_buffer_minutes` default 10) pads both sides for conflict checks.
- Calendar display: API returns events for a date range (`GET /api/calendar?from&to&teacher&room`), frontend renders (FullCalendar). Never `SELECT *` — always bounded range, max 31d.
- Availability is strictly per-venue: rules, exceptions, and resources belong to one venue, and slot computation never looks across venues. A teacher working two venues has availability per venue, via each membership.

**Data model** (all fields in §3.7):

```mermaid
erDiagram
    Resource {
        int id PK
        int venue FK
        string type
        string name
    }
    AvailabilityRule {
        int id PK
        int resource FK
        int weekday
        time start_time
        time end_time
        datetime valid_from
        datetime valid_to
    }
    AvailabilityException {
        int id PK
        int resource FK
        date date
        time start_time
        time end_time
        bool closed
    }
    Appointment {
        int id PK
        int venue FK
        int member FK
        int teacher FK
        int resource FK
        datetime starts_at
        datetime ends_at
        string status
    }
    Booking {
        int id PK
    }
    User {
        int id PK
    }
    Resource ||--o{ AvailabilityRule : opens
    Resource ||--o{ AvailabilityException : closes
    Resource ||--o{ Appointment : uses
    User ||--o{ Appointment : takes
    Appointment ||--o{ Booking : fills
```

Slots are computed (rules − exceptions − commitments); there is no slot table.

### 3.4 Passes & credits

Models: `PassProduct(name, credits_total or unlimited, validity_days, applicable_class_types M2M blank=all, transferable=False)`, `MemberPass(member, product, credits_total, credits_used, valid_from, valid_until, status)`, `CreditLedger(pass FK, booking FK NULL, delta, reason: purchase|booking|refund|forfeit|expiry|adjustment, created_by, created_at)` — ledger is append-only, balance = `SUM(delta)`.

Rules:
- Booking consumes exactly 1 credit (v1; keep `credits_cost` column default 1 for later pricing). FIFO: oldest valid pass covering the class type first. Unlimited passes checked before credit ones.
- Expiry via nightly Celery task writes `forfeit/expiry` ledger rows; never delete or mutate `credits_used` directly — always append to ledger and update cached counters in same transaction.
- Refunds append `+1 refund` rows referencing original booking. Staff adjustments require `reason` + staff id (audit).
- Race safety: `select_for_update` on chosen `MemberPass` row during booking.

**Data model** (all fields in §3.7):

```mermaid
erDiagram
    PassProduct {
        int id PK
        int venue FK
        string name
        int credits_total
        int validity_days
        bool transferable
    }
    MemberPass {
        int id PK
        int member FK
        int product FK
        int credits_total
        int credits_used
        datetime valid_from
        datetime valid_until
        string status
    }
    CreditLedger {
        int id PK
        int member_pass FK
        int booking FK
        int delta
        string reason
        int created_by FK
        datetime created_at
    }
    User {
        int id PK
    }
    ClassType {
        int id PK
    }
    Booking {
        int id PK
    }
    PassProduct ||--o{ MemberPass : issues
    User ||--o{ MemberPass : owns
    MemberPass ||--o{ CreditLedger : moves
    Booking ||--o{ CreditLedger : settles
```

`applicable_class_types` is an M2M from product to class type (blank = all). Balance is always `SUM(delta)`.

### 3.5 Aggregators (ClassPass-style)

Models: `Aggregator(name, api_token_hash, seat_allotment, cancel_cutoff_minutes, commission_percent, active)`, `AggregatorBooking(map to Booking.source=aggregator:<name>, external_id UNIQUE per aggregator)`.

Rules:
- Separate API surface: `POST /api/v1/aggregators/<slug>/bookings` with token auth (hashed, per-aggregator, rotatable) + rate limit. Allotment enforced: aggregator bookings per class ≤ `min(allotment, free seats)`.
- Idempotency required: `(aggregator, external_id)` unique; retries with same key return original booking. Webhook/cancel symmetric. Log every inbound request (`AggregatorEventLog`) for reconciliation.
- Availability push: read-only `GET .../schedule?from&to` + optional webhook on class change (Celery, retry with backoff, sign payloads HMAC).
- Aggregator bookings never consume member passes — billed to aggregator account monthly. Late-cancel policy from contract (`cancel_cutoff_minutes` per aggregator) applies instead of venue default.

**Data model** (all fields in §3.7):

```mermaid
erDiagram
    Aggregator {
        int id PK
        int venue FK
        string slug
        string api_token_hash
        int seat_allotment
        int cancel_cutoff_minutes
        float commission_percent
        bool active
    }
    AggregatorBooking {
        int id PK
        int aggregator FK
        int booking FK
        string external_id
    }
    AggregatorEventLog {
        int id PK
        int aggregator FK
        string direction
        string payload
        datetime created_at
    }
    Booking {
        int id PK
    }
    Aggregator ||--o{ AggregatorBooking : places
    Booking ||--o{ AggregatorBooking : fulfils
    Aggregator ||--o{ AggregatorEventLog : logs
```

`(aggregator, external_id)` is unique — retries return the original.

### 3.6 Access control (self-service doors)

Models: `AccessPoint(name, controller_id, venue)`, `AccessEvent(member NULL, access_point, granted bool, reason, booking_id NULL, occurred_at)`.

Rules:
- Grant iff: active pass OR confirmed booking starting within `[-15min, +class duration]` OR staff role. Deny otherwise, always log.
- Door controllers call `POST /api/access/check` (token auth per controller, p95 <200ms): read-only check, no credit deduction. Cache member validity in Redis (TTL 60s) with DB fallback; fail-closed on DB outage (deny + log) — shortcut: fail-closed only, auto-open on outage is out of scope.
- Anti-passback: same member re-entry within 60s returns prior decision without new event (configurable).

**Data model** (all fields in §3.7):

```mermaid
erDiagram
    AccessPoint {
        int id PK
        int venue FK
        string name
        string controller_id
    }
    AccessEvent {
        int id PK
        int member FK
        int access_point FK
        bool granted
        string reason
        int booking FK
        datetime occurred_at
    }
    User {
        int id PK
    }
    Booking {
        int id PK
    }
    AccessPoint ||--o{ AccessEvent : knocks
    User ||--o{ AccessEvent : attempts
    Booking ||--o{ AccessEvent : admits_via
```

`AccessEvent.member` is null for unidentified knocks; `booking` is null for pass/staff grants.

### 3.7 Field reference

Every model, every field, grouped by section. `datetime` = tz-aware UTC; `→` = FK with delete rule; enums list all values with the default starred. Relationship diagrams live in each section above.

*§2 — Tenancy, organizations & roles*

| Model | Field | Type | Rules / default |
|---|---|---|---|
| Organization | slug | string | unique |
| | name | string(200) | |
| | membership_scope | enum(*spanning, per_venue) | per org, set at onboarding |
| Venue | organization | fk→Organization cascade | slug unique per org |
| | slug | string | unique per organization, not globally |
| | name | string(200) | |
| | time_zone | string(64) | default `UTC`, display only |
| VenuePolicy | venue | fk→Venue cascade | versions, not edits: `related_name="policies"` |
| | valid_from / valid_until | datetime, null | null `valid_until` = active; retire = stamp it |
| | ― | unique (venue) | where `valid_until` is null: exactly one active row |
| | class_late_cancel_hours | int | default 8; group-class cutoff (forfeit inside window) |
| | appointment_late_cancel_hours | int | default 24; 1-1 cutoff, same forfeit rule |
| | forfeit_late_cancel | bool | default true |
| | waitlist_hold_minutes | int | default 60 |
| | booking_buffer_minutes | int | default 10 |
| Membership | organization | fk→Organization cascade | unique (org, user, venue) |
| | venue | fk→Venue null, cascade | NULL = spanning; required when scope is per_venue |
| | user | fk→User cascade | |
| | role | enum(owner, manager, teacher, frontdesk, *member) | per membership |

*§3.1 — Scheduling*

| Model | Field | Type | Rules / default |
|---|---|---|---|
| ClassType | venue | fk→Venue cascade | unique together with name |
| | name | string(200) | |
| | description | text | default empty |
| | capacity_default | int, null | fallback 2 of 3 |
| | duration_min | int | |
| Room | venue | fk→Venue cascade | unique together with name |
| | name | string(200) | |
| | capacity | int, null | fallback 3 of 3 |
| ScheduledClass | venue | fk→Venue cascade | |
| | class_type | fk→ClassType protect | |
| | room | fk→Room protect | |
| | teacher | fk→User protect | |
| | starts_at / ends_at | datetime | check ends_at > starts_at |
| | capacity_override | int, null | fallback 1 of 3 |
| | status | enum(*scheduled, cancelled, completed) | immutable once completed |
| | checkin_opens_minutes | int | default 30 |
| | ― | exclusion (venue, room) + overlap | where status ≠ cancelled |
| | ― | exclusion (venue, teacher) + overlap | where status ≠ cancelled |
| TeacherSubstitution | scheduled_class | fk→ScheduledClass cascade | append-only |
| | old_teacher / new_teacher | fk→User protect | history kept |
| | reason | string(255) | default empty |
| | created_by | fk→User null, set_null | |

*§3.2 — Bookings*

| Model | Field | Type | Rules / default |
|---|---|---|---|
| Booking | venue | fk→Venue cascade | |
| | member | fk→User cascade | |
| | scheduled_class | fk→ScheduledClass null, cascade | exactly one target set |
| | appointment | fk→Appointment null, cascade | exactly one target set |
| | status | enum(*confirmed, waitlisted, cancelled, cancelled_late, no_show, completed) | |
| | source | string(64) | default `app`; `frontdesk` or `aggregator:<slug>` |
| | idempotency_key | string(64) | unique |
| | credit_tx | fk→CreditLedger null, set_null | |
| | checked_in_at | datetime, null | |
| | ― | unique (venue, member, class) | where confirmed/waitlisted |
| | ― | unique (venue, member, appointment) | where confirmed/waitlisted |

*§3.3 — Appointments & resources*

| Model | Field | Type | Rules / default |
|---|---|---|---|
| Resource | venue | fk→Venue cascade | unique together with name |
| | type | enum(room, equipment, teacher) | |
| | name | string(200) | |
| AvailabilityRule | resource | fk→Resource cascade | |
| | weekday | int | check 0–6 (Mon–Sun) |
| | start_time / end_time | time | check end > start |
| | valid_from / valid_to | datetime, null | null = open-ended |
| AvailabilityException | resource | fk→Resource cascade | unique together with date |
| | date | date | |
| | start_time / end_time | time, null | null + closed = shut all day |
| | closed | bool | default false |
| Appointment | venue | fk→Venue cascade | |
| | member | fk→User cascade | |
| | teacher | fk→User protect | |
| | resource | fk→Resource null, protect | |
| | starts_at / ends_at | datetime | check ends_at > starts_at |
| | status | enum(*scheduled, cancelled, completed) | appt window = `appointment_late_cancel_hours` |
| | ― | exclusion (venue, teacher) + overlap | where status ≠ cancelled |
| | ― | exclusion (venue, resource) + overlap | where status ≠ cancelled |

*§3.4 — Passes & credits*

| Model | Field | Type | Rules / default |
|---|---|---|---|
| PassProduct | venue | fk→Venue cascade | unique together with name |
| | name | string(200) | |
| | credits_total | int, null | NULL = unlimited |
| | validity_days | int | |
| | applicable_class_types | m2m→ClassType, blank | blank = all types |
| | transferable | bool | default false |
| MemberPass | member | fk→User cascade | |
| | product | fk→PassProduct protect | |
| | credits_total | int, null | snapshot at purchase; NULL = unlimited |
| | credits_used | int | default 0; cache only, ledger is truth |
| | valid_from / valid_until | datetime | |
| | status | enum(*active, expired, depleted) | |
| CreditLedger | member_pass | fk→MemberPass protect | (`pass` is reserved in code; never edited, only appended) |
| | booking | fk→Booking null, set_null | |
| | delta | int | check ≠ 0; balance = SUM(delta) |
| | reason | enum(purchase, booking, refund, forfeit, expiry, adjustment) | staff adjustments need staff id + reason |
| | created_by | fk→User null, set_null | |
| | created_at | datetime | auto, immutable |

*§3.5 — Aggregators*

| Model | Field | Type | Rules / default |
|---|---|---|---|
| Aggregator | venue | fk→Venue cascade | unique together with slug |
| | name | string(200) | |
| | slug | slug | |
| | api_token_hash | string(128) | hashed, rotatable; never a user password |
| | seat_allotment | int | enforced as min(allotment, free seats) |
| | cancel_cutoff_minutes | int | contract late-cancel window |
| | commission_percent | decimal(5,2) | default 0 |
| | active | bool | default true |
| AggregatorBooking | aggregator | fk→Aggregator cascade | unique together with external_id |
| | booking | 1:1→Booking cascade | billed to aggregator, never member passes |
| | external_id | string(128) | partner reference; retries return original |
| | created_at | datetime | auto |
| AggregatorEventLog | aggregator | fk→Aggregator cascade | |
| | direction | enum(inbound, outbound) | |
| | payload | json | default `{}` |
| | created_at | datetime | auto |

*§3.6 — Access control*

| Model | Field | Type | Rules / default |
|---|---|---|---|
| AccessPoint | venue | fk→Venue cascade | unique together with controller_id |
| | name | string(200) | |
| | controller_id | string(128) | per-device token auth |
| AccessEvent | member | fk→User null, set_null | null = unidentified knock |
| | access_point | fk→AccessPoint cascade | indexed with occurred_at |
| | granted | bool | fail-closed on outage |
| | reason | string(255) | default empty; always logged |
| | booking | fk→Booking null, set_null | set for booking-window grants |
| | occurred_at | datetime | auto |

## 4. API & Project Layout

- Django 6.1 + DRF for `/api/*` (Python 3.14+, per `pyproject.toml`), `djangorestframework-simplejwt` (app) + token auth (aggregators/controllers). Versioned: `/api/v1/`. OpenAPI via `drf-spectacular`, breaking change = new version.
- Proposed layout (`django-admin startproject config .`; virtual uv project, no `src/` build — Django apps live at the repo root, SPA in `frontend/`):
  ```
  manage.py  config/ (settings/, urls.py)  organizations/ scheduling/ bookings/ passes/ aggregators/ access/  frontend/
  ```
  One app per §3 section. Cross-app imports only via services (`bookings/services.py::book_seat()`), never model-to-model shortcuts.
- Settings: `django-environ`, split `base/dev/prod`; Postgres via `psycopg` v3 + `btree_gist` (the only extension); Redis (cache + Celery broker); generated defaults kept (`USE_TZ = True`, `TIME_ZONE = 'UTC'`), `time_zone` per venue display-only, store all datetimes UTC.
- Background: Celery + Beat — waitlist promotion, expiry sweeps, aggregator webhooks, reminders/notifications (email/SMS via pluggable backend, templates per venue).
- Money-adjacent discipline: ledger append-only, `select_for_update` on booking paths, `idempotency_key` unique on `Booking`, admin actions logged (`LogEntry` + `reason`).

## 5. Quality Bar

### Django best practices
- Fat services/models, thin views: no business logic in views/serializers; services raise typed errors (`SeatFull`, `CreditInsufficient`), views map to status codes.
- Validation at trust boundary: serializers validate; constraints (`Check/Unique/Exclusion`) enforce at DB as backstop. `select_related/prefetch_related` everywhere list-shaped; assert `assertNumQueries` in list tests.
- AuthZ: `IsAuthenticated` + per-venue permission class (`IsVenueMember`) on every viewset; tests hit cross-venue access (must 404, not 403, to avoid id leaks).
- Migrations: generated, reviewed, `sqlmigrate` for exclusion constraints; data migrations batched. Never `RunPython` without reverse.
- Observability: structured logs with `venue_id/booking_id`, Sentry, `/healthz`, Prometheus metrics (`bookings_total{status}`, `door_grants_total`).

### Testing
- Unit (pytest-django + factory-boy, fast, no I/O): service functions — FIFO pass deduction, late-cancel forfeit vs refund boundary (±1 min), waitlist ordering, availability math (DST edge), allotment enforcement. Target ≥80% on `services.py`/ledger.
- Concurrency test (required, not optional): `ThreadPoolExecutor` N threads booking last seat → exactly 1 confirmed, N-1 waitlisted/409. Same for double-credit-spend.
- API tests (DRF APITestCase): happy path + 409 full + idempotent retry + cross-venue isolation + aggregator token scope.
- E2E (Playwright, few but real — full harness in §9): member books → waitlisted → staff cancels seat → member promoted + email received (mailpit); late cancel forfeits credit visible in ledger; door check grants/denies. Run in CI against the running app (web/worker processes plus docker-run db, redis, mailpit); tag `@e2e`, nightly + pre-release, not per-commit if slow.
- CI: `ruff check`, `ruff format --check`, `pytest -x`, playwright `@smoke`. Seed demo venue via management command for local dev. E2E detail lives in §9.

## 6. Build Order

1. orgs+auth (tenancy: organizations, venues, policies, memberships), 2. classes+booking tx + tests, 3. waitlist/late-cancel + Celery, 4. passes/ledger, 5. appointments/availability+calendar, 6. access control. Ship 1–4 as MVP; validate the single-venue product (1–6) before phase 2: 7. aggregators (advanced — earns its place only on a proven core). Frontend (§7) builds alongside from step 2 (schedule list first); admin scoping (§8) lands with step 1's models.

## 7. Frontend (React + TypeScript)

Full build-to contract in `SPEC-frontend.md` — summary here:

- One SPA: React 18, TypeScript strict, Vite. Server state via TanStack Query; routing via React Router. Never hand-write API DTOs: generate the client with openapi-typescript from the drf-spectacular schema in CI — schema drift breaks the build, not production.
- Same-origin serving in v1: `vite build` output served as static files by Django (WhiteNoise) — no CORS, no cookie juggling. API at `/api/*`, app at `/*`.
- Auth: simplejwt pair; short-lived access token in memory, rotating refresh in localStorage; every request carries `Authorization: Bearer` + `X-Venue-Slug`; 401 → refresh-once → login redirect. Role comes from `GET /api/v1/me` (membership role); client-side gating only — the server enforces everything. Spanning staff get a venue switcher that re-fetches on switch.
- Route map (role in brackets): `/` schedule + book [all authenticated], `/calendar` FullCalendar React on `GET /api/v1/calendar` [member, staff], `/me/passes` + `/me/ledger` [member], `/teach` my schedule [teacher], `/desk` check-in, no-show, adjustments, door log [frontdesk+], `/manage/*` classes, subs, products, policy versions, aggregators [manager, owner].
- E2E (§9) drives this SPA, not the API directly.

## 8. Django admin: sufficient, with three conditions

Verdict per user class:

| Role | Default admin? | Notes |
|---|---|---|
| owner, manager | YES, if scoped | Covers all back-office CRUD — provided (1) every ModelAdmin filters querysets to the staffer's venue(s) (`get_queryset`; default admin does NOT do this — without it venue A's staff sees venue B), (2) audit models read-only (`CreditLedger`, `AggregatorEventLog`, `AccessEvent`: no add/change/delete), (3) secrets never editable (`api_token_hash` via rotation tooling only). Staff ≠ superuser; per-model rights via Groups. |
| frontdesk | PARTIAL | Admin works as fallback, but a check-in queue needs the React `/desk` UI — admin takes ~6 clicks per check-in, unusable with a line. |
| teacher, member | NO | Never grant staff flags; React only. |
| aggregators, door controllers | NO | Token-scoped APIs only, never user accounts. |

So: build the React surfaces AND scope the admin; neither alone covers all classes.

## 9. End-to-end tests (the proving layer)

- Harness: Playwright (Python) against `web` (Django) + `frontend` (Vite preview of the production build) + `worker/beat` + db + redis + mailpit. Deterministic data: `seed_demo` once per run plus a per-run org whose `VenuePolicy` uses second-scale `waitlist_hold_minutes` — promotion tests must never sleep an hour. Late-cancel ±1min boundaries stay at unit level (freezegun); E2E uses real windows against the short test policy.
- Cases (each maps to user stories): smoke [login, book, cancel → refund visible]; promotion [full → waitlist → freed seat → promoted + mailpit receipt]; late-cancel [cancel inside window → forfeit row in ledger UI]; door [grant with booking, deny without, both rows in AccessEvent]; aggregator [same `external_id` twice → one booking; over-allotment → 409]; admin scoping [venue-A staffer cannot see venue-B rows in admin].
- Discipline: `@smoke` per-commit, full `@e2e` nightly + pre-release; trace + video on failure; mailpit assertions via its API, never sleeps past the shortened windows; assert what users see (page text, ledger rows, emails), never implementation details. Per-step E2E gates live in `SPEC-frontend.md` §6 — no frontend step is complete until its gate (new scope + all previous scopes) is green.
