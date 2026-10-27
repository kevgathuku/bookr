# Venue policies are versioned, never edited

Changing the rules retires the open row (stamps `valid_until`) and inserts
a successor; exactly one open row per venue via partial unique index, read
through `current_policy`. History is the audit trail for "what rules applied
when" disputes.

## Considered Options

- Edit the row in place: simple, but destroys the evidence for past
  forfeits and refunds the moment rules change.
- Full temporal tables with point-in-time queries: more than disputes need;
  cancels evaluate against the current policy, and the ledger already
  records what happened.

## Consequences

`activate()` (retire + insert, atomic) is the only write path; the partial
unique index is the race backstop. Venue creation must insert the first
version or every policy read raises.
