# Spec: Scoped cancellation policies and plan memberships remodel

Status: ready-for-agent

## Problem Statement

Every venue enforces exactly one versioned set of booking rules at a time: a single late-cancel window shared by all class categories, all plan types, and all venues in the organization. A yoga workshop and a daily spin class cannot have different cancellation terms; a drop-in guest and a monthly unlimited member are treated identically. Grandfathering is implemented by pinning individual members to policy versions, which is fragile and invisible. Credits live in a separate ledger keyed off a different membership shape, roles conflate "what plan did this person buy" with "what may this person do on staff", and cancelling a whole class has no clean refund-and-notify path. Operators cannot express "stricter rules for workshops, lenient rules for drop-ins" without code changes.

## Solution

Replace the single versioned venue policy with scoped cancellation rules: each rule optionally narrows by venue, class category, and plan type, and the most specific matching rule wins, with priority breaking ties. Split the old membership into two concepts: roles (what a person may do, per venue or org-wide, including owner/manager ranks) and plan memberships (what a person bought, with a credit balance backed by a re-keyed movement ledger). Log every cancellation as an event row carrying a snapshot of the rule that decided it, so later rule edits never rewrite history. Cancelling a whole class refunds everyone without penalty. Late-cancel enforcement is credit- or history-based only — there is no fee path and no payments coupling. Venue and organization slugs, and venue time zones (UTC default), stay exactly as they are.

## User Stories

Booking with credits:

1. As a member on a credit pack, I want credits deducted when I book a class, so that my balance reflects what I have left.
2. As a member on an unlimited monthly plan, I want to book without touching any credit balance, so that booking stays frictionless.
3. As a drop-in guest, I want my single-credit membership to pay for my booking like any other plan, so that guests flow through the same path as members.
4. As a comp-guest holder, I want to book without any payment reference, so that staff can invite guests freely.
5. As a member, I want booking refused when the class is full, already started, or cancelled, so that I never hold a meaningless booking.
6. As a member, I want booking refused when my plan is expired or I have no credits left, so that I know to top up first.

Cancelling (member-initiated):

7. As a member, I want to cancel for free outside the late-cancel window with my credits refunded, so that early changes cost me nothing.
8. As a member cancelling inside the window, I want the rule's enforcement applied (keep credit or strike), so that late cancels have predictable consequences.
9. As a member, I want cancelling where no rule covers my booking to succeed penalty-free and still be logged, so that uncovered categories cancel free by design, not by accident.
10. As a member, I want cancelling after the class started to be refused with direction to no-show handling, so that post-start outcomes stay consistent.

Waivers:

11. As frontdesk staff, I want to waive a member's late penalty with a reason, so that goodwill gestures are recorded, not invisible.
12. As a venue operator, I want waived penalties to keep the booking marked late-cancelled while recording who waived it, so that lateness history stays honest.

Session cancellation (whole class):

13. As a teacher, I want to cancel my own class, refunding every booked member without penalty, so that a sick day doesn't punish members.
14. As frontdesk staff, I want to cancel any class at my venue with a reason, so that operational cancellations are covered when the teacher can't.
15. As a member whose class was cancelled, I want my credit back automatically, so that I don't have to ask.
16. As a venue operator, I want repeat or concurrent session-cancel attempts to be safe (no double refunds), so that double-clicks and retries can't mint credits.

Strikes and history:

17. As a venue operator, I want strikes derived from stood strike-enforcement late cancels in the log, so that repeat-offender handling counts what actually happened — one punishment per lateness, never double jeopardy with kept credits.
18. As a venue operator, I want waived or allowed late cancels excluded from strike counts, so that forgiven lateness doesn't punish members.
19. As a venue operator, I want each cancellation record to carry the deciding rule's snapshot (window, enforcement, cutoff, initiator), so that later rule edits never rewrite history.
20. As support staff, I want to see who cancelled, in what capacity, when, under which rule, and why a penalty was waived, so that disputes are answerable.

Policy authoring:

21. As a venue operator, I want a most-specific catch-all rule (all scopes blank) as the fallback, so that every booking context resolves to something deliberate.
22. As a venue operator, I want narrower rules (e.g. workshops only, or drop-ins at one venue) to override broader ones, so that exceptions don't need duplicate rules.
23. As a venue operator, I want equally specific overlapping rules at the same priority rejected at creation, so that ambiguity is impossible, not resolved arbitrarily.
24. As a venue operator, I want rule creation to validate the same way in admin and in code, so that programmatic rule setup can't smuggle in ambiguous rules.

Roles and plans:

25. As a teacher, I want to cancel bookings in classes I teach, without penalising the member, so that I can manage my own roster without costing members credits.
26. As frontdesk staff, I want to cancel on a member's behalf per their request, applying policy normally, so that phone and desk requests work.
27. As frontdesk staff removing someone on my own decision, I want the member not penalised, so that staff decisions never cost members credits.
28. As a member, I want strangers unable to cancel my bookings, so that my bookings are safe.
29. As a venue operator, I want one person to be a member at one venue and a teacher at another, so that multi-role people are modelled correctly.
30. As a venue operator, I want org-wide roles (no venue pinned) to apply at every venue, including owner/manager ranks, so that floaters and leadership aren't re-created per location.

Platform:

31. As a venue operator, I want venue slugs and organization slugs to keep working exactly as today (routing, headers, seeds), so that the remodel doesn't break addressing.
32. As a venue operator, I want venue time zones (UTC default) validated as IANA names and used for displayed cutoffs, so that "cancel by 8pm" means local 8pm.
33. As a developer, I want cancelling to return the cancellation record (not just the booking), so that callers and tests assert on the decided outcome directly.
34. As a developer, I want side effects (notifications) to fire only after the cancel transaction commits, so that members are never notified of rolled-back cancels.
35. As a developer, I want an injectable clock on cancel operations, so that window-boundary tests don't rely on timing hacks.

## Implementation Decisions

- A single seam: the bookings-domain service layer (policy resolution, cancel paths, consequence application). Rank-to-capability interpretation lives in exactly one explicit predicates module; gates reference capabilities, never ranks. Model validation and database constraints remain the second line of defense. No new seams across apps.
- The old membership splits in two: `OrgRole` (user/organization/venue-nullable/role, with owner/manager ranks re-added alongside member/teacher/frontdesk — roles stay the single source of truth per ADR-0005) and plan `Membership` (user/plan FK `PROTECT`/credit balance/validity dates/payment reference). Staff management, venue management, and partnership management are powers of ranks, expressed through the capability predicates; Django groups remain unused.
- Cancellation rules are scoped, not versioned: each rule optionally narrows by venue, class category, and plan type, with blank meaning "any". Resolution picks the most specific matching rule (count of narrowed scopes), priority breaks ties; uncovered booking contexts cancel free and logged — a designed outcome for categories with no policy, not a misconfiguration fallback. Grandfathering by pinned version disappears; history is preserved by snapshotting the deciding rule onto each record instead.
- Enforcement is `NONE / STRIKE / LOSE_CREDIT` only. There is no fee path, no fee amount, no charger, and no payments coupling anywhere in the design. Strikes count stood `STRIKE`-enforcement lates in a rolling 30-day window (no double jeopardy with kept credits); waived rows — inline or retroactive — never count.
- The class catalogue separates the offer from the occurrence: the offering holds venue, teacher, title, category, session duration, and per-seat credit price (all immutable per session and per booking); the session holds start time, capacity, and a nullable cancelled-at timestamp. The scheduled/cancelled/completed status enum goes away — "cancelled" is a timestamp, "past" derives from start time, and session end derives from start plus offering duration. Category, price, and duration cannot vary per session or per booking.
- Every booking is paid by exactly one plan membership, which is always set: drop-ins and comps are memberships too, so there is no separate guest path. Booking creation picks the paying membership (oldest valid first, unlimited monthly before limited), checks plan validity and balance against the offering price, debits, and stamps `credits_spent` on the booking; the membership reference is protected against deletion. Retries are idempotent: no double booking, no double spend.
- The credit movement ledger is kept and re-keyed from passes onto plan memberships (all field names, reason kinds, the nonzero-delta constraint, and append-only discipline unchanged), plus one nullable link from adjustment rows to cancellation records for retroactive waivers. The per-membership balance field is a cached counter updated in the same transaction, per the existing pattern. Pass products and per-pass state die with the old models; plan validity duration lives on the plan.
- Refunds return exactly the stamped spend. Session cancel loops locked booking rows, refunds each booking its own stamped amount (mixed receipts from mid-sale repricing refund correctly; unlimited-monthly members stamped zero refund zero), releases every booking, and writes one uniform record per released booking; repeats and member-vs-session races are safe by lock plus cancelled-at guard.
- Cancelling returns the record; side effects fire only after commit; the clock is injectable. Statuses keep late-cancelled on waived and staff-decided outcomes (history honest) while penalties follow the decider: members pay for their own choice, never for a teacher's or staffer's. Desk flows carry an explicit on-behalf flag distinguishing "member requested, apply policy" from "our decision, no penalty"; contradictory waive-plus-no-penalty calls raise; staff-initiated cancels require a reason.
- Retroactive waiver (after an enforced cancel) is a compensating ledger adjustment row linked to the record — never a history rewrite. Balances move at waiver time, never backdated; one waiver adjustment per record (idempotent); the original enforced record stands as what happened at cancel time.
- No-show and check-in producers are carried over (status-only check-in; no-show writes a late record inside the post-start window derived from session end); waitlist and holds defer to a follow-up ticket, subscribing to the seat-freed event later.
- Authoring-layer guardrails make uncovered-by-mistake rare and visible: auto-created org-wide `NONE` baseline rule on org creation, last-rule-deletion protection, and an admin coverage matrix (venue × category × plan type showing the winning rule or designed-free). Lookup stays total and honest.
- Kept exactly as-is: organization and venue slugs with current uniqueness, venue time-zone field name with IANA validation and UTC default, slug-based routing/headers/seeds, and the typed-error-to-HTTP mapping (insufficient credits still surfaces as 402).
- Migration mechanics for the dev phase (no production data): fresh initial migrations per touched app with no data migrations, backfills, or archives; seed tasks rewritten for the new graph (org, venue, plans with validity, offerings, sessions, users, roles, memberships, baseline `NONE` rule). Seeds include plans plus memberships for every demo user, since the services assume a paying membership is always present. Model-level defaults are ordinary field definitions.
- Build order: roles and tenancy first, then the catalogue, then booking creation, then policy resolution plus the cancel paths, then the ledger re-key alongside, then admin, seeds, desk flows, notifications, and the factory/test migration; contract deletion of the old world; integrate and verify last.

## Testing Decisions

- A good test here asserts externally visible behavior (booking status, balance moved or kept, record contents, error raised) — never resolution internals or query shapes; tests that would break on an internals refactor without any behavior change are rejected.
- Service-layer tests with an injected clock are the primary seam: window boundaries on both sides, each enforcement type, waiver inline and retroactive, no-rule-designed-free, double-cancel and race safety, mixed-receipt session refunds, and the on-behalf/contradiction validations. Prior art is the policy-version grandfathering tests (same Given/When/Then shape, with the injectable clock replacing timing hacks).
- Rule-authoring tests cover the most-specific-wins matrix, priority tiebreaks, ambiguity rejection, and baseline-seed presence, through a creation path that runs full validation — since model validation never fires on programmatic saves, tests must go through the same validating path as the admin.
- Cascade tests cover session cancel refunding every booking its stamped amount, one uniform log row each, safe repeats, racing member cancels, and member-cancel of an already-released booking raising.
- Ledger tests cover spend/refund/adjustment rows against the balance cache, retroactive-waiver linkage and idempotency, and expiry sweeps; strike tests cover stood-`STRIKE`-only counting with waived (both kinds) excluded.
- Factories grow to cover plans, plan memberships, offerings, sessions, bookings, policies, and ledger rows alongside the existing user, organization, venue, and role factories; explicit organization-plus-venue passing is kept (no hidden derivation), and duplicate-row tests stay on direct creates.
- Every cancel call site (views, tasks, tests) moves to the keyword-argument, returns-the-record contract, with tests asserting on the record directly.

## Out of Scope

Payment processing of any kind (no fee path exists to integrate; nothing is owed to a provider); native mobile apps; marketing CRM; automatic member bans (flag-only throttling carries over); waitlist and hold mechanics (deferred to a follow-up ticket, not dropped); the check-in timestamp (status-only check-in ships); aggregator allotments against the new catalogue; frontend changes for the new rules and plans vocabulary; data migration, backfills, and history archiving (dev phase; seeds recreate everything).

## Further Notes

- The project glossary needs updating on implementation: `Membership` no longer means "a person's role" (that is now role/`OrgRole`) but "a plan a specific user bought"; versioned `Venue policy` is superseded by scoped cancellation rules; the separate `CreditLedger` is re-keyed onto plan memberships with the balance field as cache; `Strike` is now explicitly a non-waived `STRIKE`-enforcement late record; `Pass`/`PassProduct` become plan/`MembershipPlan`.
- All eleven grill decisions (plus sub-decisions: offering price and duration fields, initiator/on-behalf/reason-required semantics, re-keyed ledger with record link, plan validity duration, door-validity as monthly-valid-or-balance>0 within dates) resolved into the decisions above; the per-ticket decision pointers in the tracker now read as settled, with triggers noted where a future change reopens one (per-user waiver granularity, payments integration).
- This spec mirrors the tracked epic for the remodel; the two should be kept in sync if anything reopens.
