# Spec: Bookr venue management platform

Status: ready-for-agent

## Problem Statement

Individual venues run their business across disconnected tools and manual processes: class schedules on one system, waitlists on paper or spreadsheets, teacher substitutions by group chat, late cancellations unenforced, 1-1 appointments in a separate calendar, credit passes tracked loosely, third-party aggregators (platforms reselling the venue's classes) managed by email, and door access for self-service venues bolted on separately. The result is double-booked rooms and teachers, overfull classes, lost revenue from unenforced late cancels, front-desk overload, and no single record of who is owed what.

## Solution

A single multi-tenant Django application per the above framing that gives each venue one place to run group classes (schedule, waitlist, substitutions, late cancels), 1-1 appointments with resource availability and a calendar view, a pass-and-credit ledger backing every booking, an aggregator channel that books the same seats under contract terms, and a door-access check for self-service operation. Members get one booking flow; staff get one back office; aggregators and door controllers get narrow, token-scoped APIs.

## User Stories

Scheduling (classes):

1. As a venue manager, I want to publish a class schedule with room, teacher, and capacity, so that members can see and book what's on.
2. As a venue manager, I want the system to refuse overlapping bookings of the same room or teacher, so that I never double-book a space or a person.
3. As a venue manager, I want to adjust a class's capacity without ejecting already-confirmed members, so that I can react to demand without punishing early bookers.
4. As a venue manager, I want to cancel a class and have confirmed members refunded and notified automatically, so that a cancellation doesn't become front-desk chaos.
5. As a venue manager, I want to record a teacher substitution that keeps the history of who was originally assigned, so that payroll and accountability stay correct.
6. As a booked member, I want to be notified when my class's teacher changes or the class is cancelled, so that I am not surprised at the door.

Bookings, waitlist, late cancellations:

7. As a member, I want to book a seat in a class with one action, so that signing up takes seconds.
8. As a member, I want to join the waitlist when a class is full, so that I still have a chance to get in.
9. As a waitlisted member, I want to be promoted automatically in sign-up order when a seat frees up, so that the process is fair without staff intervention.
10. As a waitlisted member, I want a limited hold window to claim my promoted seat, so that a seat doesn't sit empty while someone dithers.
11. As a member, I want to cancel my booking outside the late-cancel window and get my credit back, so that plans changing early costs me nothing.
12. As a venue owner, I want late cancellations to forfeit the member's credit, so that late cancels stop costing me an unsellable seat.
13. As a venue owner, I want the late-cancel window configurable per venue, so that policy matches how my venue actually runs.
14. As front-desk staff, I want to mark no-shows shortly after class end with credit forfeiture, so that ghost bookings have consequences.
15. As a venue owner, I want repeat no-show members flagged for throttling, so that chronic ghosting doesn't block genuine members.
16. As front-desk staff, I want to override a forfeiture with a logged reason, so that genuine emergencies stay human while remaining auditable.
17. As a member, I want to retry a booking safely (same result, no double charge) when my network flakes, so that I never pay twice for one tap.

1-1 appointments, availability, calendar:

18. As a member, I want to book a 1-1 appointment with a teacher at a genuinely free time, so that my session actually happens.
19. As a venue manager, I want to define weekly availability rules plus one-off exceptions (holidays, closures), so that bookable times reflect reality.
20. As a venue manager, I want buffer time between appointments enforced automatically, so that back-to-back sessions don't collide.
21. As a member, I want one calendar view of classes and appointments I can filter by teacher or room, so that I can plan my week.
22. As a teacher, I want my classes and appointments to conflict-check against each other, so that I am never booked in two places at once.

Passes and credits:

23. As a venue owner, I want to sell pass products (credit bundles or unlimited, with validity windows), so that I have predictable revenue.
24. As a member, I want my bookings to consume credits from my oldest valid pass first, so that nothing expires while a newer pass gets used.
25. As a member, I want to see my passes and every credit movement (bookings, refunds, forfeits, expiry), so that I trust the balance.
26. As a venue owner, I want expired credits written off through the ledger rather than silently deleted, so that the books always reconcile.
27. As front-desk staff, I want to adjust a member's credits only with a recorded reason, so that goodwill gestures stay auditable.

Aggregators:

28. As an aggregator partner, I want to read a venue's schedule for a date range, so that I can display bookable classes on my own platform.
29. As an aggregator partner, I want to book and cancel seats idempotently within my seat allotment, so that retries never double-book and I never exceed my allocation.
30. As a venue owner, I want aggregator bookings kept off member passes and billed to the aggregator, so that the channel's economics stay separate.
31. As a venue owner, I want the aggregator's contract cutoff to govern its late cancels, so that partner terms are honored instead of venue defaults.
32. As a venue owner, I want every aggregator request logged for reconciliation, so that end-of-month billing disputes are settled with data.
33. As a venue owner, I want to rotate an aggregator's API token without downtime surprises, so that a leaked credential is a non-event.

Access control:

34. As a venue owner running self-service hours, I want the door to grant entry on an active pass, a current booking, or staff role — and deny otherwise — so that the venue runs without front-desk cover.
35. As a venue owner, I want every door attempt logged with its reason, so that I can audit who entered and why.
36. As a venue owner, I want the door to fail closed (deny) when systems are down, so that an outage never becomes an open door.
37. As a member, I want my door check to answer fast, so that I am not queuing at the entrance staring at a spinner.

Platform:

38. As a venue owner, I want my data strictly isolated from other venues on the shared platform, so that members and staff never see a neighbor's business.
39. As a staff member with access to two venues, I want my permissions scoped per venue, so that a role in one place grants nothing elsewhere.

## Implementation Decisions

- Tenancy is single-database shared-schema with a venue foreign key on every tenant-scoped row; venue resolution happens in middleware (staff profile or venue-slug header) plus a queryset mixin, and uniqueness constraints are scoped per venue. Cross-venue access returns "not found" rather than "forbidden" to avoid leaking record existence.
- One application module per domain area (tenancy incl. memberships, scheduling, bookings, passes, availability/appointments, aggregators, access); cross-module interaction goes through service-layer functions, never direct model shortcuts.
- All booking creation flows through a single booking service that runs in a database transaction with a row lock on the class, checks seats, spends credit, and creates the booking; it raises typed domain errors (seat full, insufficient credit, duplicate booking) that the web layer maps to status codes. No business logic lives in views or serializers.
- Waitlist position is derived from booking creation order rather than stored counters; promotion runs as an idempotent background job with a per-venue hold window, and the same promotion path serves cancellations, no-shows, and capacity increases.
- The credit ledger is append-only: balances derive from the sum of ledger rows (purchase, booking, refund, forfeit, expiry, adjustment), cached counters update in the same transaction, and expiry sweeps and staff adjustments write rows rather than editing history. Booking spends the oldest valid applicable pass first, unlimited passes before credit bundles.
- Availability is computed from weekly rules minus exceptions minus existing commitments at request time; slots are never persisted. Conflict prevention for rooms, teachers, and resources uses range-exclusion constraints at the database level (requires Postgres with range-index support), with buffer time folded into conflict checks.
- Aggregators get a separate versioned API surface with per-partner hashed tokens, rate limiting, per-class seat allotments, idempotency on the partner's external booking reference, a full inbound request log, and signed change webhooks with retried delivery. Aggregator bookings bypass member passes entirely.
- The door check is a read-only, token-authenticated endpoint per controller that grants on active pass, current booking window, or staff role; member validity is cached briefly with database fallback, re-entry within a short window replays the prior decision, and the check fails closed on outage. Every attempt is logged.
- Background work (waitlist promotion, credit expiry sweeps, aggregator webhooks, member notifications via a pluggable mail/message backend with per-venue templates) runs on a task queue with a scheduler; datetimes are stored in UTC with per-venue display time zones.
- API versioning starts at v1 with an OpenAPI schema; authentication is short-lived user tokens for the app and scoped long-lived tokens for aggregators and door controllers.
- Build order: tenancy first, then classes plus the booking transaction, then waitlist and late cancels, then the credit ledger, then appointments and calendar, then aggregators, then access control. The first four areas constitute the shippable MVP.

## Testing Decisions

- A good test here asserts externally visible behavior (seat granted or refused, credit moved or forfeited, door granted or denied), not implementation details; tests that would break on a refactor of internals without any behavior change are rejected.
- Service-layer tests cover FIFO credit deduction, the late-cancel refund/forfeit boundary on both sides, waitlist ordering and hold expiry, availability math including daylight-saving edges, and aggregator allotment enforcement, with a coverage target on service and ledger logic.
- The concurrency tests are mandatory, not optional: many threads racing for the last seat must yield exactly one confirmation, and racing spends of the last credit must yield exactly one booking. The codebase is greenfield so there is no prior art; these tests become the reference examples for later test authors.
- API tests cover the happy path, full-class refusal with waitlist offer, idempotent retries, cross-venue isolation, and aggregator token scoping.
- End-to-end tests (browser automation against a composed environment with database, cache, web, worker, and test mailbox) cover book-then-waitlist-then-promotion with email receipt, late-cancel forfeiture visible in the ledger, and door grant/deny; the full E2E set runs nightly and pre-release with a fast smoke subset in per-commit CI alongside lint, type-checking, and the unit suite.
- A demo-seed command builds a one-venue fixture (room, teacher, members) reused by tests, local development, and E2E.

## Out of Scope

Payment processing and PSP integration; native mobile apps; dynamic or surge pricing (one credit per booking in v1, with a cost column reserved); marketing CRM; automatic member bans (flag-only throttling in v1); auto-open doors on system outage (fail-closed only); class-type-specific pricing; pass transfers between members.

## Further Notes

- Postgres with range-exclusion support plus Redis (cache and task broker) are hard infrastructure requirements; the exclusion constraints do not work on SQLite, so development and CI must run real Postgres from day one.
- MVP is tenancy through the credit ledger; aggregators and access control build on the booking and ledger seams and must not start before ledger balances reconcile.
- The tutorial walkthrough for this build lives alongside this spec and follows the same chapter order.
