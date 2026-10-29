# No-double-booking enforced by exclusion constraints, not app checks

Overlapping room or teacher assignments are refused by Postgres
`EXCLUDE USING gist` over `TSTZRANGE(starts_at, ends_at)` — evaluated inside
the write itself — instead of read-then-write overlap checks in Python.

## Considered Options

- Application-level checks with row locks: correct only when every writer
  remembers the lock; one forgotten path double-books.
- Serializing through a queue: correct but turns every booking into async
  work with user-visible latency.

## Consequences

Requires Postgres with `btree_gist` from day one (SQLite can never do this),
installed via a `CreateExtension` migration so fresh and test databases
self-build. The `condition=` (Django 6.1) and unique constraint names are
load-bearing details, not style.
