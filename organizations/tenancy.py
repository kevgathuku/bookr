"""Shared tenancy plumbing: venue-scoped querysets + venue-role guard.

Cross-organization or cross-venue access is a 404, never a 403 (no id leaks).

Resolution lives here (not only in middleware) because DRF token/JWT auth
runs after all middleware: with the SPA's simplejwt header auth, the
middleware only ever sees AnonymousUser. The middleware resolves for
session users; permissions lazily resolve for the rest via ensure_venue.
"""

import dataclasses

from django.db import models

from organizations.capabilities import OPERATE_DESK_ROLES
from organizations.models import Organization, OrgRole, Venue

VENUE_HEADER = "X-Venue-Slug"


@dataclasses.dataclass(frozen=True)
class ResolvedVenue:
    """Venue resolution: the venue, its organization, and the user's
    role rows behind the decision. Venue and organization are None
    when nothing the user holds covers the request."""

    venue: Venue | None
    organization: Organization | None
    org_roles: list


def _match_pinned(rows, slug):
    for row in rows:
        if row.venue is not None and row.venue.slug == slug:
            return row.venue, row.venue.organization
    return None, None


def _match_spanning(rows, slug):
    for row in rows:
        if row.venue is None:
            venue = (
                Venue.objects.filter(organization=row.organization, slug=slug)
                .select_related("organization")
                .first()
            )
            if venue is not None:
                return venue, venue.organization
    return None, None


def _default_venue(rows):
    pinned = [row for row in rows if row.venue_id is not None]
    pinned.sort(key=lambda row: row.role not in set(OPERATE_DESK_ROLES))
    if pinned:
        return pinned[0].venue, pinned[0].venue.organization
    return None, None


def resolve_venue(user, slug):
    """Resolve the request venue and the role rows behind the decision."""
    org_roles = list(
        OrgRole.objects.filter(user=user).select_related(
            "venue",
            "venue__organization",
            "organization",
        ),
    )
    if slug:
        venue, organization = _match_pinned(org_roles, slug)
        if venue is None:
            venue, organization = _match_spanning(org_roles, slug)
        return ResolvedVenue(
            venue=venue, organization=organization, org_roles=org_roles
        )
    venue, organization = _default_venue(org_roles)
    return ResolvedVenue(venue=venue, organization=organization, org_roles=org_roles)


def ensure_venue(request):
    """Request venue, resolving late for DRF-authenticated users."""
    venue = getattr(request, "venue", None)
    if venue is None and request.user.is_authenticated:
        resolved = resolve_venue(request.user, request.headers.get(VENUE_HEADER))
        request.venue = resolved.venue
        request.organization = resolved.organization
        request.org_roles = resolved.org_roles
        return resolved.venue
    return venue


def covers(row, venue):
    if row.venue_id == venue.pk:
        return True
    return row.venue_id is None and (row.organization_id == venue.organization_id)


class VenueScopedQuerySet(models.QuerySet):
    def for_venue(self, venue):
        return self.filter(venue=venue)
