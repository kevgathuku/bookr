# Plan memberships own the money trail; ledger re-keyed, spend stamped

A plan membership (user, plan, credit balance, validity dates) is the
sole payer for its bookings — drop-ins and comps included, so there is
no guest path. Booking creation debits the offering price from the
paying membership and stamps the spent amount on the booking; refunds
return exactly the stamp, which makes mixed receipts (mid-sale
repricing, unlimited members stamped zero) correct without price
lookups. The credit ledger is kept and re-keyed from passes onto plan
memberships; the per-membership balance stays a cached counter updated
in the same transaction. Retroactive waivers are compensating ledger
rows linked to the record — history is never rewritten.

Relates to 0002 (append-only ledger mechanics, preserved as-is).

## Considered Options

- Fresh adjustment table for waivers: duplicates ledger semantics minus
  the history; rejected in favor of re-keying the existing table.
- Fee enforcement alongside: rejected — no provider exists, so fees
  would couple the domain to nothing for zero volume.

## Consequences

Pass products and per-pass state are deleted; plan validity duration
lives on the plan. Every credit movement (spend, refund, expiry,
adjustment) must write its ledger row in the booking's transaction.
Reviewers should treat balance edits without a ledger row, or ledger
rows without a paying membership, as a bug.
