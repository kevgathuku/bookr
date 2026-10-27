# Append-only credit ledger; balance is always derived

Credits move only as new ledger rows (purchase, booking, refund, forfeit,
expiry, adjustment). No balance column is ever edited; `credits_used` on the
pass is a cache. The balance is whatever the rows sum to.

## Considered Options

- Mutable balance column: one UPDATE per booking, but double-spends and
  silent adjustments become possible and history is lost.
- Event sourcing with projections: the same discipline with heavier
  machinery than this ledger needs.

## Consequences

Refunds, expiry, and staff adjustments are all just rows with reasons, so
billing disputes settle by reading history. The invariant test (sums equal
cached counters) must hold on seed data or nothing downstream is trustworthy.
