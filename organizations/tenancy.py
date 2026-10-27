"""Shared tenancy plumbing: venue-scoped querysets + venue-membership guard.

Cross-organization or cross-venue access is a 404, never a 403 (no id leaks).

Resolution lives here (not only in middleware) because DRF token/JWT auth
runs after all middleware: with the SPA's simplejwt header auth, the
middleware only ever sees AnonymousUser. The middleware resolves for
session users; permissions lazily resolve for the rest via _ensure_venue.
"""

from django.db import models

STAFF_ROLES = frozenset(("owner", "manager", "teacher", "frontdesk"))
VENUE_HEADER = "X-Venue-Slug"


def _match_pinned(memberships, slug):
    for membership in memberships:
        if membership.venue is not None and membership.venue.slug == slug:
            return membership.venue, membership.venue.organization
    return None, None


def _match_spanning(memberships, slug):
    from organizations.models import Venue

    for membership in memberships:
        if membership.venue is None:
            venue = (
                Venue.objects.filter(
                    organization=membership.organization,
                    slug=slug,
                )
                .select_related("organization")
                .first()
            )
            if venue is not None:
                return venue, venue.organization
    return None, None


def _default_venue(memberships):
    pinned = [mem for mem in memberships if mem.venue_id is not None]
    pinned.sort(key=lambda mem: mem.role not in STAFF_ROLES)  # staff first
    if pinned:
        return pinned[0].venue, pinned[0].venue.organization
    return None, None


def resolve_venue(user, slug):
    """Return (venue, organization, memberships) for an authenticated user."""
    from organizations.models import Membership

    memberships = list(
        Membership.objects.filter(user=user).select_related(
            "venue",
            "venue__organization",
            "organization",
        ),
    )
    if slug:
        venue, organization = _match_pinned(memberships, slug)
        if venue is None:
            venue, organization = _match_spanning(memberships, slug)
        return venue, organization, memberships
    venue, organization = _default_venue(memberships)
    return venue, organization, memberships


def _ensure_venue(request):
    """Request venue, resolving late for DRF-authenticated users."""
    venue = getattr(request, "venue", None)
    if venue is None and request.user.is_authenticated:
        resolved = resolve_venue(request.user, request.headers.get(VENUE_HEADER))
        request.venue = resolved[0]
        request.organization = resolved[1]
        request.memberships = resolved[2]
        venue = resolved[0]
    return venue


def _covers(membership, venue):
    if membership.venue_id == venue.pk:
        return True
    return membership.venue_id is None and (
        membership.organization_id == venue.organization_id
    )


class VenueScopedQuerySet(models.QuerySet):
    def for_venue(self, venue):
        return self.filter(venue=venue)
