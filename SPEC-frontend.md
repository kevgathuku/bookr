# Bookr Frontend Spec — React + TypeScript SPA

Companion to `SPEC.md` (§7 summary). This is the build-to contract: stack,
every endpoint the UI needs (including staff APIs the backend spec implies
but never names — those are flagged NEW), auth, routes, state rules, and
what "done" means per page. Versions below mean "latest stable at
implementation time, then pinned in `frontend/package.json`."

## 1. Stack & layout

- React 18 + TypeScript `strict` + Vite. Routing: React Router. Server
  state: TanStack Query only (no redux/zustand — server data lives in the
  cache, UI ephemera in `useState`). Calendar: FullCalendar React.
  Styling: CSS Modules + a token file (`--space`, `--color-*`); no component
  library in v1 — semantic HTML you can keyboard through.
- Layout (`frontend/src/`): `routes/` (one folder per route, co-located
  loader/components), `components/` (shared only: Button, Dialog, Field,
  EmptyState, DataTest ids), `api/generated/` (codegen output, never
  hand-edited), `api/client.ts` (base fetch: base URL, auth + venue headers,
  refresh-on-401), `hooks/`, `test/e2e/` (Playwright, `@smoke`/`@e2e` tags).
- Quality gates (CI, same workflow as backend): `tsc --noEmit`, eslint,
  `openapi-typescript` regen + `git diff --exit-code` (schema drift breaks
  the build), `vite build`, Playwright `@smoke`.
- Serving: `vite build` → Django WhiteNoise, same origin (`/api/*` API,
  `/*` app). No CORS in v1. E2E runs against Vite `preview` of the
  production build + Django + worker + db + redis + mailpit (SPEC §9).

## 2. API contract (everything the UI calls)

Base: `/api/v1`, JSON, `Authorization: Bearer <access>` (except login/
refresh), `X-Venue-Slug: <slug>` on every call. Errors: `409` seat full
(with `{"waitlist": true}` offered via `POST /bookings?waitlist=true`),
`402` no credit, `404` also means "not yours" (never distinguish).

Auth & me:
`POST /auth/login {username, password} → {access, refresh}`,
`POST /auth/refresh {refresh} → {access, refresh(rotated)}`,
`GET /me → {user, memberships: [{organization, venue|null, role}]}`.
Logout is client-side (clear storage). Access token in memory, refresh in
localStorage; 401 → refresh once → retry → else redirect `/login`.

Member flow (stories 7–11, 17–18, 21, 24–25, 37):
`GET /classes?venue&from&to`, `GET /calendar?from&to&teacher&room`,
`GET /availability-slots?teacher&resource&from&to` (**NEW** — backend §3.3
defines the computation, not the endpoint),
`POST /bookings {class|appointment, idempotency_key: <client uuid>}`,
`GET /bookings?mine`, `POST /bookings/:id/cancel {reason?}`,
`GET /me/passes`, `GET /me/ledger`, `GET /policy` (current windows, for
displaying "free cancel until …").

Frontdesk `/desk` (stories 14, 16, 27, 34–35):
`POST /bookings/:id/checkin`, `POST /bookings/:id/no_show`,
staff cancel = same cancel endpoint + `reason` (manager/owner/frontdesk
only, always refunds), `GET /ledger?member=`,
`POST /passes/grant {member, product}` (**NEW** — no-payments v1 "sell" =
staff grant writing a `purchase` ledger row),
`GET /access/events?from&to` (door log).

Teach `/teach` (stories 5–6, 22): `GET /classes?teacher=me&from&to`,
`GET /appointments?teacher=me`, substitution history read-only.

Manage `/manage/*` (stories 1–4, 12–13, 15, 23, 26, 31–33, 35, 40, 43 —
all **NEW** endpoints, backend must add alongside):
classes `POST/PATCH/DELETE /classes`, `POST /classes/:id/substitutions`;
products `POST/PATCH /pass-products`; policy `GET /policy/versions`,
`POST /policy/versions` (→ `activate()`); adjustments
`POST /ledger/adjustments {member_pass, delta, reason}` (reason required);
aggregators `GET/POST/PATCH /aggregators`, `POST /aggregators/:id/rotate`
(returns the single plaintext viewing of the new token),
`GET /aggregators/:id/bookings`, `GET /aggregator-events`; access points
`GET /access/points`; memberships `GET /memberships` (roster).

Partner/door APIs (no UI): aggregator booking/cancel/schedule feed and
`POST /api/access/check` per SPEC §§3.5–3.6.

## 3. State & data rules

- Query keys start with scope: `["venue", slug, ...]`. Venue switch
  invalidates everything below it. After every mutation, invalidate the
  screens it affects (`book` → classes, calendar, bookings, passes,
  ledger); never optimistic-write bookings, credits, or ledger rows —
  server truth only, then refetch.
- Time: API speaks UTC; display via `Intl` in `venue.time_zone` (from
  `/me`). Countdowns ("free cancel until 18:00") derive from policy +
  start time, recomputed on render — never stored.
- Client validation mirrors server rules for UX (capacity display, window
  math) but enforces nothing; every 4xx renders the server's message.
- Empty/error/offline states are designed per route, not an afterthought:
  each page spec below names its empty state.

## 4. Pages & acceptance

- `/` schedule [all]: list classes in range, seats-left badges, one-tap
  book/waitlist; full class offers waitlist inline. Empty: "No classes this
  week." Done: book → 409 → waitlist → visible in bookings.
- `/calendar` [member, staff]: FullCalendar month/week, teacher+room
  filters, click-through to book. Done: matches list data, <31d bounds.
- `/bookings`, `/me/passes`, `/me/ledger` [member]: bookings with cancel
  buttons + refund/forfeit receipts; passes with expiry; ledger as plain
  append-only history. Done: every credit movement visible with reason.
- `/teach` [teacher]: my upcoming classes + appointments + sub history.
  Done: cross-checked against calendar, no double display.
- `/desk` [frontdesk+]: today's classes, per-class roster with
  check-in/no-show one-tappers, late-cancel override with reason field,
  member lookup + credit adjust + door log tail. Done: full queue flow
  keyboard-only in under 5s per member (the admin-takes-6-clicks bar).
- `/manage/*` [manager, owner]: CRUD classes/subs/products/policy
  versions (retire/activate shown as history, never edit-in-place)/
  aggregators + token rotation + reconciliation log. Done: every story
  1–4, 12–13, 23, 26, 31–33, 35, 40, 43 clickable without the admin.
- `/login`, venue switcher, 404/403/500 pages, loading skeletons. Done:
  401 → refresh → retry → login; switcher re-fetches; no white screens.
- Accessibility floor: semantic landmarks, focus moved to page title on
  route change, all actions reachable by keyboard, color never the only
  signal (status text always present).

## 5. Test hooks & build order

- `data-testid` on: book/waitlist/cancel buttons, seat counts, ledger
  rows, check-in/no-show buttons, grant/deny badges, venue switcher.
  Determinism per SPEC §9 (seeded org, second-scale hold windows).
- Build order: auth shell + `/` schedule/booking (member core) →
  calendar/passes/ledger → `/desk` → `/teach` → `/manage/*` →
  hardening (a11y pass, skeleton/error states, codegen gate).
  Each step ends with its page's Done criteria green under `@smoke`.

## 6. Verification gates (E2E after every step)

No step is complete until its gate is green, and no later step starts on
red. Each gate runs its new scope *plus all previous scopes* (regression
is part of every gate, not a phase at the end).

| After step | Gate: must all pass |
|---|---|
| Auth shell + `/` booking | `tsc`, eslint, codegen diff clean, `vite build`; E2E login, venue switch re-fetches, book seat, full class → 409 → waitlist join → visible in bookings |
| Calendar / passes / ledger | Above scopes still green, plus: calendar matches list API for the same range; passes show expiry; every booking/cancel shows its ledger row with reason |
| `/desk` | Above scopes still green, plus: roster check-in and no-show one-tappers, late-cancel override with reason, credit adjust with reason visible in ledger, door log tail renders |
| `/teach` | Above scopes still green, plus: teacher schedule matches API, sub history shows original teacher |
| `/manage/*` | Above scopes still green, plus: class CRUD, sub create, product create, policy retire→activate shown as history, aggregator create + token rotation (single plaintext viewing), adjustment requires reason |
| Hardening | Full `@smoke` + full `@e2e` (SPEC §9) green in one run |

Deterministic preconditions, every gate run (skip one and the gate means
nothing): fresh `seed_demo`; per-run org with second-scale
hold windows; mailpit purged via its API; fixed viewport + venue timezone;
`--retries=0 --workers=1` (retries hide flakes, parallelism races seats);
trace + video on, kept on failure only.

Flake rule: a gate failing intermittently *twice* is a bug, not luck — in
product or test, quarantined with a ticket, never re-run-to-green. A gate
may only be waived in writing with the waived scope named and re-gated
before release.
