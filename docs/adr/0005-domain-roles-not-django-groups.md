# Domain roles live on Membership, not in Django Groups

Authorization reads the `role` field on the membership row — in domain code
and in the admin (via custom `has_*_permission` methods). Django's `Group`
model is deliberately unused: groups are global, so per-tenant roles would
need synthetic `org-42-manager` rows, leaking tenant structure into shared
tables and sprawling with every signup.

## Considered Options

- Groups per role per tenant: integrates with stock admin permissions, but
  doubles every membership change into group bookkeeping and breaks the
  single-source rule the moment they disagree.
- Third-party object-permission packages: heavier machinery than five roles
  and one join table need.

## Consequences

No code may branch on group membership; reviewers should treat any
`user.groups` usage as a bug. If a future integration genuinely requires
Django permissions, map them read-only from roles — never the reverse.
