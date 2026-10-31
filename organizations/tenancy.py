"""Shared tenancy plumbing: venue-scoped querysets + venue-role guard.

Cross-organization or cross-venue access is a 404, never a 403 (no id leaks).

Resolution lives here (not only in middleware) because DRF token/JWT auth
runs after all middleware: with the SPA's simplejwt header auth, the
middleware only ever sees AnonymousUser. The middleware resolves for
session users; permissions lazily resolve for the rest via ensure_venue.
"""

from django.db import models

VENUE_HEADER = "X-Venue-Slug"


def _match_pinned(rows, slug):
    for row in rows:
        if row.venue is not None and row.venue.slug == slug:
            return row.venue, row.venue.organization
    return None, None


def _match_spanning(rows, slug):
    from organizations.models import Venue

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
    pinned.sort(key=lambda row: row.role not in _staff_values())
    if pinned:
        return pinned[0].venue, pinned[0].venue.organization
    return None, None


def _staff_values():
    from organizations.models import OrgRole

    return {OrgRole.Role.OWNER, OrgRole.Role.MANAGER, OrgRole.Role.FRONTDESK}


def resolve_venue(user, slug):
    """Return (venue, organization, org_roles)."""
    from organizations.models import OrgRole

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
        return venue, organization, org_roles
    venue, organization = _default_venue(org_roles)
    return venue, organization, org_roles


def ensure_venue(request):
    """Request venue, resolving late for DRF-authenticated users."""
    venue = getattr(request, "venue", None)
    if venue is None and request.user.is_authenticated:
        venue, organization, org_roles = resolve_venue(
            request.user, request.headers.get(VENUE_HEADER)
        )
        request.venue = venue
        request.organization = organization
        request.org_roles = org_roles
        return venue
    return venue


def covers(row, venue):
    if row.venue_id == venue.pk:
        return True
    return row.venue_id is None and (row.organization_id == venue.organization_id)


class VenueScopedQuerySet(models.QuerySet):
    def for_venue(self, venue):
        return self.filter(venue=venue)
