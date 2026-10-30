# Rank is interpreted once, in capability predicates

Owner and manager return as `OrgRole` ranks (member, teacher, frontdesk,
manager, owner). What each rank may do is defined exactly once, in an
explicit capability-predicates module (`can_operate_desk`,
`can_manage_staff`, `can_waive`, …); every gate — services, views, admin,
desk flows — references capabilities and never lists ranks. Penalties
follow the decider: a member's own choice (or frontdesk acting explicitly
on their behalf) is judged by policy; a teacher's or staffer's own
decision never costs the member.

This extends 0005 (domain roles are the single source of truth): no code
may branch on Django groups, and any future stock-permission need is met
by mapping read-only from roles — never the reverse.

## Considered Options

- Django groups for back-office authority: keeps the custom tenancy
  scoping regardless, adds dual-write split-brain between role rows and
  groups, and sprawls per-tenant or leaks cross-tenant.
- Scope instead of rank (org-wide frontdesk ≈ manager): cannot express
  the owner/manager split the business needs.

## Consequences

Adding a rank touches the predicates module and nothing else — unless
the new rank needs new powers, which is then one deliberate line.
Reviewers should treat rank literals outside the predicates module, or
any `user.groups` usage, as a bug.
