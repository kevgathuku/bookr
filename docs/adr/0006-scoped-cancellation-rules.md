# Scoped cancellation rules replace versioned policies

Booking rules are scoped rows (optional venue, class category, plan type)
resolved most-specific-wins with priority tiebreaks — not successive
versions of one venue-wide policy. Every cancellation writes a record
carrying a snapshot of the deciding rule, so later rule edits never
rewrite history. Grandfathering by pinned version is deleted: no booking
is judged by anything but the rules live at cancel time.

Uncovered booking contexts (no rule matches, e.g. a category with no
policy) cancel free and logged — a designed outcome, not a gap. An
org-wide allow-lateness baseline is seeded per organization; ambiguity
(equally specific overlapping rules at the same priority) is rejected at
creation. There is no fee enforcement and no payments coupling anywhere
in the design.

## Considered Options

- Per-plan terms owned by the membership: unrepresentable gaps on the
  plan axis, but loses venue and category dimensions and reopens
  grandfathering on every plan edit.
- Fee enforcement via a payments integration: couples the domain to a
  provider that does not exist, for zero volume; deferred until a real
  integration needs it.

## Consequences

Supersedes 0004 (versioned venue policy). Authoring paths must validate
like the admin; tests must resolve through the same validating path.
Reviewers should treat any pinned-policy or fee-shaped code as a bug.
