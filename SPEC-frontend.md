# Spec: Bookr member & staff SPA

Status: ready-for-agent

## Problem Statement

Members and staff run the venue through a web UI that has to stay truthful
about a fast-moving backend: seats fill, waitlists promote, holds expire,
credits move on every booking and cancel, policies version underfoot. The
previous frontend contract described an aspirational build (React 18,
eslint, unwritten endpoints, month views, offline states) that drifted
from what actually shipped. This spec documents the SPA as it exists and
is used: what each role sees, what each action does, and where the UI
deliberately stops and defers to the server.

## Solution

One React 19 + TypeScript strict + Vite SPA (TanStack Query, React Router,
FullCalendar React), served same-origin by Django (no CORS in v1), styled
with Tailwind v4 design tokens. One shared shell (sidebar, venue chip,
credits chip) wraps every route; every page follows the same card/list
language, venue-time display, and empty/error states. Members get one
booking flow across schedule and calendar; frontdesk gets one roster
screen; managers get one manage screen; teachers get one schedule view.
No optimistic writes anywhere — the server answers, then the UI refetches.

## User Stories

Shell, auth, venue context:

1. As a visitor, I want a centered login card that reports bad credentials
   in plain language, so that I know whether to retry or ask staff.
2. As a signed-in user, I want a sidebar showing my current venue and its
   time zone, so that I always know which venue's schedule I am looking at.
3. As a member of several venues, I want a venue switcher that refetches
   everything below it, so that I never see one venue's data under another
   venue's name.
4. As a member, I want a credits-left chip in the sidebar, so that I know
   before browsing whether I can afford a class.
5. As a member with bookings, I want a count badge on My bookings, so that
   I notice upcoming classes without opening the page.
6. As any user, I want a 404 page with a way back and an error page with a
   retry button, so that I never stare at a blank screen.

Schedule (member core):

7. As a member, I want a 7-day strip with per-day tabs defaulting to the
   earliest day that has classes, so that I land on something bookable
   instead of an empty today.
8. As a member, I want Prev/Next week navigation, so that I can plan beyond
   the current seven days.
9. As a member, I want to filter by teacher and room, so that I can follow
   a favorite teacher or stick to one studio.
10. As a member, I want an "only bookable" toggle, so that full classes
    disappear when I just want a seat.
11. As a member, I want each class to show its time range and duration in
    venue time, so that I never convert time zones in my head.
12. As a member, I want spots-left pills and a capacity meter on every
    class, so that scarcity is visible before I tap.
13. As a member, I want the credit price shown next to Book, so that the
    cost is never a surprise.
14. As a member, I want to book with one tap, so that signing up takes
    seconds.
15. As a member booking a full class, I want the waitlist offered inline
    after the full response, so that I still have a chance to get in.
16. As a booked member, I want a Booked pill instead of a Book button, so
    that I never double-book by accident.
17. As a member, I want an honest empty state when nothing is on, so that
    an empty day reads as empty, not broken.

Calendar:

18. As a member, I want a week grid rendered in venue time, so that the
    grid agrees with the schedule list down to the minute.
19. As a member, I want the same teacher and room filters as the schedule,
    so that both views answer the same question.
20. As a member, I want to click an event and get a booking card for it, so
    that the calendar books, not just displays.
21. As a member, I want brand-colored controls and event blocks, so that
    the grid reads as part of the app, not a widget.

Bookings, passes, ledger:

22. As a member, I want my active bookings with Confirmed/Waitlisted pills,
    so that I see status at a glance.
23. As a waitlisted member, I want my hold expiry shown in venue time, so
    that I know exactly how long I have to claim the seat.
24. As a member, I want one Cancel button per booking with the refund rule
    explained beside it, so that I know what cancelling costs.
25. As a member, I want cancelling inside the window explained as a refund
    and late cancels as forfeits, so that the policy is visible where I act.
26. As a member, I want my passes with status, remaining credits, expiry in
    venue time, and a depletion meter, so that I trust the balance.
27. As a member, I want every credit movement with its signed amount,
    reason, and note, so that any charge is traceable.
28. As a member, I want failures to show the server's message, so that I
    act on the real reason (full, no credits) instead of guessing.

Teach:

29. As a teacher, I want my upcoming classes with room and venue-time
    start, so that I know where to be.
30. As a teacher, I want my appointments listed separately, so that 1-1
    sessions don't hide among classes.
31. As a teacher, I want my substitution history with old and new teacher,
    so that cover arrangements stay visible.

Front desk:

32. As front-desk staff, I want a per-day roster with member, class, time,
    and status, so that I can work the door from one screen.
33. As front-desk staff, I want one-tap check-in and no-show buttons per
    row, so that a queue keeps moving.
34. As front-desk staff, I want check-ins visibly marked, so that I never
    check the same person in twice.
35. As front-desk staff, I want late-cancel override behind a reason field
    that blocks empty reasons, so that emergencies stay human and auditable.
36. As front-desk staff, I want member lookup with a pass picker and a
    reason-gated adjustment form, so that goodwill credits stay auditable.
37. As front-desk staff, I want the door log tail with granted/denied
    pills, so that entry decisions are scannable.

Manage (manager, owner):

38. As a venue manager, I want to create classes by picking type, room,
    teacher, and times, so that publishing takes one form.
39. As a venue manager, I want the class list with per-class delete, so
    that schedule mistakes are reversible.
40. As a venue manager, I want to assign substitutes from a form, so that
    cover is recorded with history.
41. As a venue manager, I want to create pass products and rename them
    inline, so that pricing evolves without tickets.
42. As a venue manager, I want policy versions shown as history with an
    activate-new-version form, so that rules are never edited in place.
43. As a venue owner, I want to create aggregator partners, rotate tokens
    with the single plaintext viewing, and read the per-partner call log,
    so that the reseller channel is self-serve.
44. As a venue manager, I want member lookup embedded in Manage, so that
    adjustments never require switching screens.

## Implementation Decisions

- Stack is React 19 + TypeScript strict + Vite, React Router v8, TanStack
  Query only (no store library — server data lives in the cache, UI
  ephemera in `useState`), FullCalendar 6 React for the grid, Tailwind v4
  with `@theme` tokens (brand indigo, ok/amber/bad). Package manager is
  pnpm; quality gates are biome, `tsc --noEmit`, vitest, `vite build`.
- FullCalendar renders IANA zones as UTC unless a timezone plugin is
  registered, so the app ships `@fullcalendar/moment-timezone` and passes
  `venue.time_zone` through; the grid, the schedule, and the selection
  card all resolve the zone from the same helper.
- Auth is a short token pair: access token in memory, refresh token in
  `localStorage`, `X-Venue-Slug` header on every call, refresh-once on
  401 then redirect to `/login`. Logout is client-side storage clear.
  Invite-claim (bookr-0vc): no public signup — staff presets the member
  in admin, and `/claim` (link form, or set-password form on `?uid&token`)
  drives `POST /api/v1/auth/password-reset/` + `.../password-reset-confirm/`.
  Held seats (bookr-c37): promotion seats the queue head as Held (no spend)
  and `POST /api/v1/bookings/{id}/confirm/` charges the pass and flips Held
  to Booked; decline/lapse/cancel-of-held releases as unclaimed. Bookings
  shows a Held pill + Confirm button; Schedule badges Held rows.
  The API client is hand-written (`api/client.ts`); OpenAPI types are
  generated (`generate:api` script) but behavior is never code-generated.
- The shell owns venue context: switcher clears the query cache; the
  venue chip shows slug plus time zone; the credits chip sums active
  passes; the bookings badge counts confirmed plus waitlisted rows.
- Query keys start with the venue scope; mutations invalidate and refetch
  instead of optimistic-writing bookings, credits, or ledger rows. Booking
  idempotency keys come from `crypto.randomUUID` per tap; 409 surfaces
  the waitlist action, 402 the no-credit message, always the server text.
- The API speaks UTC; display goes through `Intl` in `venue.time_zone`
  everywhere, including day grouping, hold expiries, pass expiries, and
  ledger dates. Unknown zones throw rather than silently rendering UTC.
- One shared component set (Button with primary/outline, Pill in four
  tones, Field, EmptyState, ErrorText with `role="alert"`, SkeletonList
  with `aria-busy`): pages compose cards and lists, never raw elements.
  Status is never color-only; every pill carries text.
- Accessibility floor: semantic landmarks, focus moved to `<main>` on
  route change, every action keyboard-reachable, inputs share base styles
  from the stylesheet layer.
- Route guards: the schedule redirects logged-out users to login; desk
  and manage require staff roles; teach links gate on the teacher role.
  Every tenant denial answers 404 (never 403), so the UI has no forbidden
  page by design.

## Testing Decisions

- A good test asserts externally visible behavior (seat booked, pill
  shown, message rendered), not implementation details; Testing Library
  queries by testid, role, or text, never by class name.
- Vitest covers booking flows (one-tap book posts the class id, 409
  reveals the waitlist action), day grouping and filtering, spots pills,
  the zone-grouping invariant (pinned UTC so local midnights never
  straddle a UTC day boundary), booking states, pass/ledger rendering
  with venue-time dates, and the route-UX shell (skeletons, 404, error
  boundary retry, focus move). Shared renders wrap providers; cleanup
  runs after every test so renders never leak across cases.
- Prior art for new page tests is the schedule suite (fetch mocks in
  call order: data query first, bookings second, mutation response
  last).
- End-to-end runs pytest plus Playwright (import-skipped when browsers
  are absent) against the live Django server serving the built SPA
  same-origin, seeded with the fixed demo cast; `@smoke` per commit,
  full `@e2e` nightly and pre-release.
- `data-testid` hooks are a contract: schedule, class/waitlist/book
  buttons, booked badge, roster and door rows, check-in/no-show/override
  buttons, member lookup fields, venue switcher, ledger and pass rows,
  agg token display, calendar selection.

## Out of Scope

Appointment booking from the SPA (appointments are read-only in Teach;
only classes book); staff pass grants (desk adjusts, never issues);
month view (week grid only); multi-day grouping in the schedule (one
day at a time); Cancel on the schedule card (cancels live in My bookings
with the refund messaging); offline support; countdown displays; native
mobile apps; payment processing.

## Further Notes

- This spec replaces an aspirational contract that named React 18,
  eslint, a Dialog component, a `hooks/` directory, `/me/*` routes, a
  codegen drift gate, and Playwright-only E2E. Actual: React 19, biome,
  no Dialog, one `hooks.ts`, `/passes` + `/ledger` + `/bookings` routes,
  codegen types with a hand-written client, pytest-driven E2E with
  Playwright inside. Anything still citing the old shape is stale.
- Venue time display is load-bearing: the one visual bug found in review
  was FullCalendar silently falling back to UTC, caught by comparing the
  grid against the schedule for the same venue and fixed with the
  timezone plugin, not by restyling.
- The demo seed builds the world this UI expects: spanning downtown-dance
  plus per-venue uptown-box, eight fixed logins, passes issued, classes
  across the week, and bookings in every visible state. See README.
