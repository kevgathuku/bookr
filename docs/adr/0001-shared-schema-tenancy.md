# Shared-schema tenancy with venue rows, not schemas per tenant

One Postgres database serves all organizations; every tenant row carries its
venue, venues carry their organization, and cross-tenant access answers 404
— never 403 — so existence never leaks.

## Considered Options

- Schema-per-tenant: stronger isolation, but migrations fan out per schema
  and shared operations (aggregator feeds, platform metrics) get painful.
- Single global namespace with no tenancy: rejected immediately, venues
  would see each other.

## Consequences

Membership scope (spanning vs per-venue) lives on the organization because
the choice is per business, not per member. The 404 rule constrains every
viewset and the admin: filtering to the request venue must happen before
permission checks, not as part of them.
