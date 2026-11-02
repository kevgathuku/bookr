# Bookr

How venues sell and fill classes and door access on one platform.

> Reflects the approved scoped-policies + plan-memberships remodel
> (`spec-remodel.md`). Entries marked **(remodelled)** changed meaning;
> **(new)** entries did not exist before; dropped entries describe removed
> concepts (versioned policy history, per-pass state, substitutions).

## Language

**Organization**:
The business running venues on the platform.
_Avoid_: tenant, account, company

**Venue**:
One location where classes happen.
_Avoid_: gym, club

**Cancellation rule** (remodelled):
A scoped booking rule: optional venue, class category, and plan-type
narrowing plus a late-cancel window and an enforcement. The most specific
matching rule wins; blank scope means "any".
_Avoid_: settings, config, versioned policy

**OrgRole** (new):
A person's duties at an organization, optionally pinned to one venue.
`venue=None` means the role applies org-wide. Ranks are member, teacher,
frontdesk, manager, owner. Roles never carry plan ownership.
_Avoid_: account, staff flag

**Membership** (remodelled):
A plan a specific user bought: credit balance, validity dates, payment
reference. Drop-ins and comps are memberships too (one credit, no separate
guest path). Every booking is paid by exactly one membership.
_Avoid_: account, enrollment

**Org-wide role** (remodelled):
A role with no venue pin, applying at every venue of its organization.
_Avoid_: global membership

**Member**:
A person entitled to book, holding a plan membership.
_Avoid_: customer, client

**Plan** (remodelled):
A named product a membership is bought on: monthly unlimited, credit pack,
drop-in, or comp. Carries the validity duration; per-seat pricing lives on
the offering, not the plan.
_Avoid_: package, subscription, pass product

**Class offering** (new):
The "what": venue, teacher, title, category, session duration, and
per-seat credit price. Immutable per session and per booking.
_Avoid_: class type

**Class session** (new):
The "when": one occurrence of an offering with a start time, capacity,
and a nullable cancelled-at timestamp. Ended-ness derives from start plus
offering duration.
_Avoid_: scheduled class

**Booking**:
A member's claim on one class session, paid by exactly one membership.
_Avoid_: reservation, order

**Cancellation record** (new):
One row per cancellation: who, in what capacity, when, under which rule
(or none), what was enforced or forgiven, and a snapshot of the deciding
rule. Written once, never updated; later waivers are compensating ledger
rows, not edits.
_Avoid_: log entry

**Waitlist**:
The first-come queue for a full class. Cancel paths free the seat the
queue head subscribes to.
_Avoid_: standby list

**Hold**:
The window a promoted waitlister has to claim the seat; lapses sweep
back to the queue.
_Avoid_: timeout

**Late cancel**:
A cancellation inside the rule's cutoff window. Consequence follows the
rule's enforcement, never a fixed credit forfeit.
_Avoid_: late drop

**No-show**:
A booking neither attended nor cancelled, recorded once the session's end
window passes.
_Avoid_: ghost booking

**Strike** (remodelled):
A stood, non-waived late cancellation under strike enforcement, counted
from the record log over a rolling window. Kept credits and paid fees are
their own punishment and never double-count.
_Avoid_: flag

**Credit ledger**:
The append-only record of credit movements, keyed off plan memberships
(spend, refund, forfeit, expiry, adjustment). The per-membership balance
field is a cached counter updated in the same transaction, never edited
directly.
_Avoid_: balance, wallet

**Aggregator**:
A third-party platform reselling a venue's classes.
_Avoid_: partner, reseller

**Allotment**:
The seats per session reserved for one aggregator.
_Avoid_: quota

**Access event**:
One recorded door grant-or-deny decision.
_Avoid_: log entry
