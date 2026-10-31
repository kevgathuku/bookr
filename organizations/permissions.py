"""Venue-membership API guard. 404s, never 403s (no id leaks)."""

from rest_framework import permissions
from rest_framework.exceptions import NotFound, PermissionDenied

from organizations.capabilities import can_operate_desk
from organizations.models import OrgRole
from organizations.tenancy import covers, ensure_venue


def staff_covering(request, venue):
    """True when the user holds a staff role covering the venue.

    OrgRole rows are the single source: any non-member role counts as
    staff here; desk-only gates use can_operate_desk directly.
    """
    return any(
        row.role != OrgRole.Role.MEMBER and covers(row, venue)
        for row in getattr(request, "org_roles", ())
    )


class IsVenueMember(permissions.BasePermission):
    """Filter-then-404: role covering request.venue, else NotFound."""

    message = "No such venue."

    def has_permission(self, request, view):
        venue = ensure_venue(request)
        if venue is None or not request.user.is_authenticated:
            raise NotFound(self.message)
        rows = list(getattr(request, "org_roles", ()))
        for row in rows:
            if covers(row, venue):
                return True
        # Unreachable: resolve_venue only returns venues a row covers —
        # kept fail-closed (never 403) if tenancy semantics change.
        raise NotFound(self.message)  # pragma: no cover


class IsStaff(permissions.BasePermission):
    """Back-office: staff-only for reads and writes alike."""

    message = "Staff only."

    def has_permission(self, request, view):
        venue = ensure_venue(request)
        # Unreachable: IsVenueMember always precedes IsStaff and raises
        # first on missing venue/anonymous users — kept fail-closed.
        if venue is None or not request.user.is_authenticated:  # pragma: no cover
            raise NotFound("No such venue.")
        if not staff_covering(request, venue):
            raise PermissionDenied(self.message)
        return True


def _capability_covering(request, venue, capable):
    """OrgRole rows go through the capability predicate."""
    covered = [
        row.role for row in getattr(request, "org_roles", ()) if covers(row, venue)
    ]
    return capable(covered)


class IsDesk(permissions.BasePermission):
    """Front-desk operations: operate-desk capability covering the venue."""

    message = "Front desk only."

    def has_permission(self, request, view):
        venue = ensure_venue(request)
        # Unreachable: IsVenueMember always precedes IsDesk and raises
        # first on missing venue/anonymous users — kept fail-closed.
        if venue is None or not request.user.is_authenticated:  # pragma: no cover
            raise NotFound("No such venue.")
        if not _capability_covering(request, venue, can_operate_desk):
            raise PermissionDenied(self.message)
        return True
