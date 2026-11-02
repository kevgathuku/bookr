# Frontend contract delta (remodel follow-up, bookr-9pt)

The scoped-policies + plan-memberships remodel changed the backend
contract out from under the SPA. The UI was migrated in bookr-9pt; this
note records what moved, what was deleted on purpose, and what UI work
(if any) remains. The generated snapshot
(`frontend/src/api/generated/schema.d.ts`) is regenerated from the
live schema — never hand-edited.

## Endpoint map (old → new)

- `GET /api/v1/classes/` → `GET /api/v1/sessions/` (same `from`/`to`
  window params). Session shape: `offering_title` (not `class_type_name`),
  no room (calendar serializes `room: null`; the room filters are gone).
- `GET /api/v1/me/passes/` and `GET /api/v1/passes/?member=` →
  `GET /api/v1/memberships/` and `GET /api/v1/memberships/?member=`
  (staff only). Membership shape: `plan_name`, `credits_remaining`,
  `starts_on`/`ends_on` (not `product_name`, `credits_total/used`).
- `POST /api/v1/bookings/` body `{scheduled_class, idempotency_key}` →
  `{session}`, with `?waitlist=true` to queue on full GROUP sessions.
  Booking shape: `session`/`session_title`, statuses `booked` (not
  `confirmed`) and `waitlisted`. Cancel posts `{}` (member) or
  `{staff_override, reason}` (desk).
- `GET /api/v1/bookings/?mine=true` — unchanged path, new shape.
- `GET /api/v1/ledger/` — unchanged path; entries key on `membership`
  (not `member_pass`).
- `POST /api/v1/ledger/adjust/` (new): desk goodwill path,
  `{membership, delta, reason}`, reason required.
- `GET /api/v1/calendar/` — unchanged; only `kind: "session"` events.

## Deleted surfaces (models retired under .7, not migrated)

Pass products, policy versions, substitutions, rooms, class types,
appointments. Managing those lives in the Django admin now; the Manage
page keeps partner aggregators + member lookup only, and Teach lists
sessions (no appointments, no sub history).

## Testids

Stable across the migration on purpose (`schedule`, `class-row`,
`book-button-*`, `waitlist-button-*`, `booked-badge`, `teach-class-row`,
`agg-*`, `roster-*`, `member-*`, `ledger-row`, `pass-row`): e2e asserts
flows, never selectors. Keep it that way.

## Residual follow-ups (none blocking)

- The Passes tab still says "passes"; the model is Membership.
- Selling a membership has no UI (admin only); desk can only adjust.
- Teacher session-cancel has no UI (API/admin only).
- Fee enforcement (bookr-55d) has no UI when it lands.
