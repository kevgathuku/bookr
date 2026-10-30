# Spec: Scoped cancellation policies and plan memberships remodel

Status: ready-for-agent

## Problem Statement

Every venue enforces exactly one versioned set of booking rules at a time: a single late-cancel window shared by all class categories, all plan types, and all venues in the organization. A yoga workshop and a daily spin class cannot have different cancellation terms; a drop-in guest and a monthly unlimited member are treated identically. Grandfathering is implemented by pinning individual members to old policy versions, which is fragile and invisible. Credits live in a separate ledger app, roles conflate "what plan did this person buy" with "what may this person do on staff", and cancelling a whole class has no clean refund-and-notify path. Operators cannot express "stricter rules for workshops, lenient rules for drop-ins" without code changes.

## Solution

Replace the single versioned venue policy with scoped cancellation rules: each rule optionally narrows by venue, class category, and plan type, and the most specific matching rule wins, with priority breaking ties. Split the old membership into two concepts: roles (what a person may do, per venue or org-wide) and plan memberships (what a person bought, with a credit balance). Log every cancellation as an event row carrying a snapshot of the rule that decided it, so later rule edits never rewrite history. Cancelling a whole class refunds everyone without penalty. Venue and organization slugs, and venue time zones, stay exactly as they are.

## User Stories

Booking with credits:

1. As a member on a credit pack, I want one credit deducted when I book a class, so that my balance reflects what I have left.
2. As a member on an unlimited monthly plan, I want to book without touching any credit balance, so that booking stays frictionless.
3. As a drop-in guest, I want my single-credit membership to pay for my booking like any other plan, so that guests flow through the same path as members.
4. As a comp-guest holder, I want to book without any payment reference, so that staff can invite guests freely.
5. As a member, I want booking refused when the class is full, already started, or cancelled, so that I never hold a meaningless booking.
6. As a member, I want booking refused when my plan is expired or I have no credits left, so that I know to top up first.

Cancelling (member-initiated):

7. As a member, I want to cancel for free outside the late-cancel window with my credit refunded, so that early changes cost me nothing.
8. As a member cancelling inside the window, I want the rule's enforcement applied (keep credit, strike, or fee), so that late cancels have predictable consequences.
9. As a member, I want cancelling with no matching rule to succeed penalty-free and still be logged, so that gaps in rule coverage fail open, not closed.
10. As a member, I want cancelling after the class started to be refused with direction to no-show handling, so that post-start outcomes stay consistent.

Waivers and fees:

11. As frontdesk staff, I want to waive a member's late penalty with a reason, so that goodwill gestures are recorded, not invisible.
12. As a venue operator, I want waived penalties to keep the booking marked late-cancelled while recording who waived it, so that lateness history stays honest.
13. As a venue operator, I want fee enforcement to charge the late fee through the payments integration, so that money follows policy.
14. As a venue operator, I want a failed fee charge to leave the booking untouched rather than half-cancelled, so that money and state never disagree.

Session cancellation (whole class):

15. As a teacher, I want to cancel my own class, refunding every booked member without penalty, so that a sick day doesn't punish members.
16. As frontdesk staff, I want to cancel any class at my venue with a reason, so that operational cancellations are covered when the teacher can't.
17. As a member whose class was cancelled, I want my credit back automatically, so that I don't have to ask.
18. As a venue operator, I want repeat or concurrent session-cancel attempts to be safe (no double refunds), so that double-clicks and retries can't mint credits.

Strikes and history:

19. As a venue operator, I want strikes derived from the cancellation log (late, non-waived), so that repeat-offender handling counts what actually happened.
20. As a venue operator, I want waived or allowed late cancels excluded from strike counts, so that forgiven lateness doesn't punish members.
21. As a venue operator, I want each cancellation record to carry the deciding rule's snapshot (window, enforcement, fee, cutoff), so that later rule edits never rewrite history.
22. As support staff, I want to see who cancelled, when, under which rule, and why a penalty was waived, so that disputes are answerable.

Policy authoring:

23. As a venue operator, I want a most-specific catch-all rule (all scopes blank) as the fallback, so that every booking context resolves to something deliberate.
24. As a venue operator, I want narrower rules (e.g. workshops only, or drop-ins at one venue) to override broader ones, so that exceptions don't need duplicate rules.
25. As a venue operator, I want equally specific overlapping rules at the same priority rejected at creation, so that ambiguity is impossible, not resolved arbitrarily.
26. As a venue operator, I want fee enforcement to require a fee amount, so that misconfigured rules are caught before they bite.
27. As a venue operator, I want rule creation to validate the same way in admin and in code, so that programmatic rule setup can't smuggle in ambiguous rules.

Roles and plans:

28. As a teacher, I want to cancel bookings in classes I teach, so that I can manage my own roster.
29. As frontdesk staff, I want to cancel on a member's behalf, so that phone and desk requests work.
30. As a member, I want strangers unable to cancel my bookings, so that my bookings are safe.
31. As a venue operator, I want one person to be a member at one venue and a teacher at another, so that multi-role people are modelled correctly.
32. As a venue operator, I want org-wide roles (no venue pinned) to apply at every venue, so that floaters aren't re-created per location.

Platform:

33. As a venue operator, I want venue slugs and organization slugs to keep working exactly as today (routing, headers, seeds), so that the remodel doesn't break addressing.
34. As a venue operator, I want venue time zones validated as IANA names and used for displayed cutoffs, so that "cancel by 8pm" means local 8pm.
35. As a developer, I want cancelling to return the cancellation record (not just the booking), so that callers and tests assert on the decided outcome directly.
36. As a developer, I want side effects (notifications) to fire only after the cancel transaction commits, so that members are never notified of rolled-back cancels.
37. As a developer, I want an injectable clock on cancel operations, so that window-boundary tests don't rely on timing hacks.

## Implementation Decisions

- Cancellations, policy resolution, and consequence application live in one bookings-domain service layer: the single seam for all cancel outcomes. Model validation and database constraints remain the second line of defense. No new seams across apps; existing model and validation seams are reused.
- The old membership splits in two: roles (what a person may do, per venue or org-wide, never pinned to a policy version) and plan memberships (what a person bought: plan, credit balance, validity dates, payment reference). The staff role set is member, teacher, and frontdesk only.
- Cancellation rules are scoped, not versioned: each rule optionally narrows by venue, class category, and plan type, with blank meaning "any". Resolution picks the most specific matching rule (count of narrowed scopes), priority breaks ties, and grandfathering by pinned version disappears — history is preserved instead by snapshotting the deciding rule onto each cancellation record.
- The class catalogue separates the offer from the occurrence: the offering holds venue, teacher, title, and category (immutable per session and per booking); the session holds start time, capacity, and a nullable cancelled-at timestamp. The scheduled/cancelled/completed status enum goes away with it — "cancelled" is a timestamp (which also records when), and "past" derives from start time.
- Every booking is paid by exactly one plan membership, which is always set: drop-ins and comps are memberships too, so there is no separate guest path. The membership reference is protected against deletion so a booking's policy can never silently change.
- Credits move at booking time (spend) and at cancel time (refund unless the penalty keeps the credit); unlimited monthly plans bypass the balance entirely. Fee enforcement delegates to the payments integration; strike enforcement needs no extra write because the cancellation record itself is the strike.
- Cancelling a whole class is a distinct path from a member cancel: nobody is penalised, everyone booked is refunded and released, and each released booking gets its own log row marked as session-caused. Repeating a session cancel is safe, and a member cancel racing a session cancel cannot double-refund.
- Side effects fire only after the cancel transaction commits, so notifications can never describe rolled-back state. A failed fee charge rolls back the whole cancel, leaving the booking untouched.
- Late-but-allowed outcomes (waived penalties, allow-lateness rules) keep the late-cancelled status with the waiver recorded, so lateness history stays honest while strike counting excludes forgiven rows.
- Kept exactly as-is: organization and venue slugs with current uniqueness, venue time-zone field name with IANA validation, and slug-based routing, headers, and seed generation throughout.
- Migration mechanics for the dev phase (no production data): fresh initial migrations per touched app with no data migrations, backfills, or archives; seed tasks rewritten for the new graph (organization, venue, plans, offerings, sessions, users, roles, memberships, baseline rules). Seeds include at least one org-wide baseline rule per organization and plans plus memberships for every demo user, since the services assume a paying membership is always present. Model-level defaults (time zone, capacity, booked status, zero credits) are ordinary field definitions.
- Build order: tenancy and roles first, then the catalogue, then policy resolution plus the cancel services, then booking creation, then admin, seeds, and the factory/test migration.

## Testing Decisions

- A good test here asserts externally visible behavior (booking status, credit moved or kept, record written, error raised), not resolution internals or query shapes; tests that would break on an internals refactor without any behavior change are rejected.
- Service-layer tests with an injected clock are the primary seam: window boundaries on both sides, each enforcement type, waiver, no-rule default, double-cancel idempotency, and member-cancel racing session-cancel. Prior art is the policy-version grandfathering tests (same Given/When/Then shape, with the injectable clock replacing timing hacks).
- Rule-authoring tests cover the most-specific-wins matrix, priority tiebreaks, ambiguity rejection, and fee-requires-amount, through a creation path that runs full validation — since model validation never fires on programmatic saves, tests must go through the same validating path as the admin.
- Cascade tests cover session cancel refunding every booking, one log row per released booking, safe repeats, and member-cancel of an already-released booking raising.
- Factories grow to cover plans, plan memberships, offerings, sessions, bookings, and policies alongside the existing user, organization, venue, and role factories; explicit organization-plus-venue passing is kept (no hidden derivation), and duplicate-row tests stay on direct creates.
- Every cancel call site (views, tasks, tests) moves to the keyword-argument, returns-the-record contract, with tests asserting on the record directly.

## Out of Scope

Payment processing and PSP integration (fail-closed rollback semantics are in scope; the charge itself is not); native mobile apps; marketing CRM; automatic member bans (flag-only throttling carries over); waitlist and hold mechanics, and the check-in flow (neither has a counterpart in the new design — confirming the drop or re-adding is a product decision, not implementation work); aggregator allotments against the new catalogue; the missing session end underpinning any carried-forward no-show time window; frontend changes for the new rules and plans vocabulary; data migration, backfills, and history archiving (dev phase; seeds recreate everything).

## Further Notes

- The project glossary needs updating on implementation: `Membership` no longer means "a person's role" (that is now role/OrgRole) but "a plan a specific user bought"; versioned `Venue policy` is superseded by scoped cancellation rules; the separate `Credit ledger` becomes the credit-balance field; `Strike` is now explicitly a non-waived late cancellation record.
- Open decisions (none blocks starting schema plus resolution work; each gates its own follow-up): venue time-zone default (current UTC vs Europe/Madrid operating assumption); default-allow vs default-deny when no rule matches; one-credit-per-booking invariant vs stamped spend amount on the booking; home for old owner/manager authority; teacher cancelling any booking in their class; waiver gating (role-only vs role plus a declared object permission, with the correct app label); strike-count treatment of waived rows (queries must be explicit); failed-fee rollback vs cancel-plus-debt (scaffold assumes rollback); session-cancel log shape for analytics (distinct minimal shape vs full snapshot); fate of waitlist, holds, and check-in; basis for any no-show time window without a session end.
- This spec mirrors the tracked issue for the remodel; the two should be kept in sync as decisions resolve.
